#!/usr/bin/env ruby
# frozen_string_literal: true

# Run actionlint without its oversized-stdin ShellCheck transport, then apply
# the same ShellCheck policy directly to regular temporary files. This keeps
# schema, expression, Python, and shell validation while avoiding the deadlock
# tracked by rhysd/actionlint#712.

require "json"
require "open3"
require "tempfile"
require "yaml"

QUEUE_DIAGNOSTIC =
  'unexpected key "queue" for "concurrency" section\. expected one of "cancel-in-progress", "group"'
SHELLCHECK_EXCLUSIONS = "SC1091,SC2194,SC2050,SC2153,SC2154,SC2157,SC2043"

class WorkflowLintError < StandardError; end

def load_workflow(path)
  document = YAML.safe_load(
    File.read(path, encoding: "UTF-8"),
    permitted_classes: [],
    permitted_symbols: [],
    aliases: true
  )
  raise WorkflowLintError, "#{path}: workflow document must be a mapping" unless document.is_a?(Hash)

  document
rescue Psych::Exception, SystemCallError => error
  raise WorkflowLintError, "#{path}: could not read workflow YAML: #{error.message}"
end

def validate_concurrency_queue!(path, label, concurrency)
  return unless concurrency.is_a?(Hash) && concurrency.key?("queue")
  return if concurrency["queue"] == "max"

  raise WorkflowLintError,
        "#{path}: #{label} concurrency queue must be exactly max, got #{concurrency['queue'].inspect}"
end

def validate_queue_contract!(path, workflow)
  validate_concurrency_queue!(path, "workflow", workflow["concurrency"])
  jobs = workflow["jobs"]
  return unless jobs.is_a?(Hash)

  jobs.each do |job_name, job|
    next unless job.is_a?(Hash)

    validate_concurrency_queue!(path, "job #{job_name}", job["concurrency"])
  end
end

def windows_runner?(job)
  Array(job["runs-on"]).any? do |label|
    normalized = label.to_s.downcase
    normalized == "windows" || normalized.start_with?("windows-")
  end
end

def effective_shell(workflow, job, step)
  step["shell"] ||
    job.dig("defaults", "run", "shell") ||
    workflow.dig("defaults", "run", "shell") ||
    (windows_runner?(job) ? "pwsh" : "bash")
end

def shellcheck_dialect(shell)
  return shell if ["bash", "sh"].include?(shell)
  return "bash" if shell.start_with?("bash ")
  return "sh" if shell.start_with?("sh ")

  nil
end

def sanitize_expressions(script)
  sanitized = script.dup
  offset = 0
  while (start_index = sanitized.index("${{", offset))
    end_index = sanitized.index("}}", start_index)
    break unless end_index

    length = end_index + 2 - start_index
    sanitized[start_index, length] = sanitized[start_index, length].gsub(/[^\r\n]/, "_")
    offset = start_index + length
  end
  sanitized
end

def shell_scripts(path, workflow)
  jobs = workflow["jobs"]
  return enum_for(__method__, path, workflow) unless block_given?
  return unless jobs.is_a?(Hash)

  jobs.each do |job_name, job|
    next unless job.is_a?(Hash) && job["steps"].is_a?(Array)

    job["steps"].each_with_index do |step, index|
      next unless step.is_a?(Hash) && step["run"].is_a?(String)

      dialect = shellcheck_dialect(effective_shell(workflow, job, step).to_s)
      next unless dialect

      step_name = step["name"].to_s.strip
      step_name = (index + 1).to_s if step_name.empty?
      yield path, job_name.to_s, step_name, dialect, step["run"]
    end
  end
end

def run_actionlint(paths)
  executable = ENV.fetch("ACTIONLINT", "actionlint")
  arguments = [
    "-shellcheck=",
    "-ignore",
    QUEUE_DIAGNOSTIC,
    *paths
  ]
  stdout, stderr, status = Open3.capture3(executable, *arguments)
  return 0 if status.success?

  warn stdout unless stdout.empty?
  warn stderr unless stderr.empty?
  status.exitstatus || 2
rescue SystemCallError => error
  raise WorkflowLintError, "actionlint could not start: #{error.message}"
end

def run_shellcheck(path, job_name, step_name, dialect, script)
  setup = dialect == "bash" ? "set -eo pipefail" : "set -e"
  source = "#{setup}\n#{sanitize_expressions(script)}\n"
  executable = ENV.fetch("SHELLCHECK", "shellcheck")
  stdout = stderr = nil
  status = nil

  Tempfile.create(["actionlint-shellcheck-", ".#{dialect}"]) do |file|
    file.chmod(0o600)
    file.write(source)
    file.flush
    stdout, stderr, status = Open3.capture3(
      executable,
      "--norc",
      "-f",
      "json",
      "-x",
      "--shell",
      dialect,
      "-e",
      SHELLCHECK_EXCLUSIONS,
      file.path
    )
  end

  unless [0, 1].include?(status.exitstatus)
    detail = stderr.to_s.strip
    detail = "exit #{status.exitstatus}" if detail.empty?
    raise WorkflowLintError, "#{path}: ShellCheck failed for job=#{job_name} step=#{step_name}: #{detail}"
  end

  findings = JSON.parse(stdout)
  raise JSON::ParserError, "top-level result is not an array" unless findings.is_a?(Array)

  findings.each do |finding|
    script_line = [finding.fetch("line").to_i - 1, 1].max
    message = finding.fetch("message").to_s.delete_suffix(".")
    warn(
      "#{path}: shellcheck reported issue in job=#{job_name} step=#{step_name}: " \
      "SC#{finding.fetch('code')}:#{finding.fetch('level')}:#{script_line}:" \
      "#{finding.fetch('column')}: #{message}"
    )
  end
  findings.length
rescue JSON::ParserError, KeyError => error
  raise WorkflowLintError,
        "#{path}: invalid ShellCheck JSON for job=#{job_name} step=#{step_name}: #{error.message}"
rescue SystemCallError => error
  raise WorkflowLintError, "ShellCheck could not start: #{error.message}"
end

def lint(paths)
  raise WorkflowLintError, "usage: lint_github_workflows.rb WORKFLOW..." if paths.empty?

  workflows = paths.to_h do |path|
    workflow = load_workflow(path)
    validate_queue_contract!(path, workflow)
    [path, workflow]
  end
  actionlint_status = run_actionlint(paths)
  return actionlint_status unless actionlint_status.zero?

  findings = workflows.sum do |path, workflow|
    shell_scripts(path, workflow).sum do |script_path, job_name, step_name, dialect, script|
      run_shellcheck(script_path, job_name, step_name, dialect, script)
    end
  end
  findings.zero? ? 0 : 1
rescue WorkflowLintError => error
  warn "ERROR: #{error.message}"
  2
end

exit lint(ARGV)
