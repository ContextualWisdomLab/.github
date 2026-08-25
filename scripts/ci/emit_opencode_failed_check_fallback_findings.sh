#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
	echo "usage: $0 <failed-check-evidence-file> [repo-root]" >&2
	exit 64
fi

EVIDENCE_FILE="$1"
REPO_ROOT="${2:-${GITHUB_WORKSPACE:-$PWD}}"
finding_index=0
tmp_files=()
unmapped_strix_reports_file="$(mktemp)"
tmp_files+=("$unmapped_strix_reports_file")

cleanup() {
	rm -f "${tmp_files[@]}"
}
trap cleanup EXIT

normalize_source_path() {
	local raw_path="$1"
	local candidate

	candidate="$(printf '%s' "$raw_path" | sed -E 's#^/workspace/[^/]+/##; s#^/tmp/strix-pr-scope\.[^/]+/##; s#^\./##; s#^/##')"
	case "$candidate" in
		services/*.py)
			candidate="backend/$candidate"
			;;
		src/*)
			if [ -e "${REPO_ROOT%/}/frontend/$candidate" ]; then
				candidate="frontend/$candidate"
			fi
			;;
	esac
	printf '%s' "$candidate"
}

first_existing_line() {
	local path="$1"
	local pattern="${2:-}"
	local match=""

	if [ ! -f "${REPO_ROOT%/}/$path" ]; then
		printf '1'
		return 0
	fi
	if [ -n "$pattern" ]; then
		match="$(grep -nE -- "$pattern" "${REPO_ROOT%/}/$path" | head -n 1 || true)"
		if [ -n "$match" ]; then
			printf '%s' "${match%%:*}"
			return 0
		fi
	fi
	printf '1'
}

strip_ansi_file() {
	local source_file="$1"

	perl -pe 's/\x1b\[[0-9;?]*[A-Za-z]//g' "$source_file"
}

get_validated_pr_diff_range() {
	local repo_root="${REPO_ROOT%/}"
	local base_sha="${PR_BASE_SHA:-}"
	local head_sha="${PR_HEAD_SHA:-${HEAD_SHA:-HEAD}}"

	if ! git -C "$repo_root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
		return 1
	fi
	if [ -z "$base_sha" ]; then
		return 1
	fi
	if ! git -C "$repo_root" rev-parse --verify "${base_sha}^{commit}" >/dev/null 2>&1; then
		return 1
	fi
	if ! git -C "$repo_root" rev-parse --verify "${head_sha}^{commit}" >/dev/null 2>&1; then
		return 1
	fi

	printf '%s...%s' "$base_sha" "$head_sha"
}

pr_changes_trusted_strix_inputs() {
	local diff_range
	local diff_status

	diff_range="$(get_validated_pr_diff_range)" || return 1
	set +e
	git -C "${REPO_ROOT%/}" diff --quiet "$diff_range" -- \
		.github/workflows/strix.yml \
		opencode.jsonc \
		scripts/ci/strix_quick_gate.sh \
		scripts/ci/test_strix_quick_gate.sh \
		requirements-strix-ci.txt
	diff_status=$?
	set -e

	if [ "$diff_status" -eq 1 ]; then
		return 0
	fi
	return 1
}

derive_location_from_report() {
	local title="$1"
	local endpoint="$2"
	local target="$3"
	local raw_location="$4"
	local clean_location=""
	local path=""
	local line=""
	local line_range=""

	if [ -n "$raw_location" ]; then
		clean_location="$(normalize_source_path "$raw_location")"
		path="${clean_location%:*}"
		line_range="${clean_location##*:}"
		line="${line_range%%-*}"
		if [ -f "${REPO_ROOT%/}/$path" ] && [[ "$line" =~ ^[0-9]+$ ]]; then
			printf '%s\t%s\t%s' "$path" "$line" "$raw_location"
			return 0
		fi
	fi

	if [[ "$target" =~ (backend/[^[:space:]]+|frontend/[^[:space:]]+|\.github/[^[:space:]]+|scripts/[^[:space:]]+) ]]; then
		path="$(normalize_source_path "${BASH_REMATCH[1]}")"
	elif [[ "$endpoint" =~ ^/services/.*\.py$ ]]; then
		path="$(normalize_source_path "${endpoint#/}")"
	fi

	if [ -n "$path" ] && [ -f "${REPO_ROOT%/}/$path" ]; then
		line="$(first_existing_line "$path")"
		printf '%s\t%s\t%s' "$path" "$line" "target/endpoint: ${target:-$endpoint}"
		return 0
	fi

	case "$title" in
		*"docker_entrypoint.sh"*|*"Docker Runtime Failure"*)
			path="Dockerfile"
			line="$(first_existing_line "$path" '^CMD \["/app/scripts/docker_entrypoint\.sh"\]|^ENTRYPOINT .*docker_entrypoint\.sh')"
			;;
		*"Path Traversal"*Attachment*|*"attachment"*filename*)
			path="backend/services/email_parser.py"
			line="$(first_existing_line "$path" 'filename = part\.get_filename\(\)|"filename":')"
			;;
		*"OIDC"*|*"session token"*|*"Session Token"*)
			path="frontend/src/lib/oidc-session.ts"
			line="$(first_existing_line "$path" 'sessionStorage\.setItem')"
			;;
		*"Prompt"*Studio*|*"Prompt Injection"*)
			path="frontend/src/app/prompt-studio/page.tsx"
			line="$(first_existing_line "$path" "apiClient\\.post|testResult|setTestResult")"
			;;
		*"Frontend Security Issues"*|*"Hardcoded Credentials"*|*"Insecure Data Handling"*)
			path="frontend/next.config.ts"
			line="$(first_existing_line "$path" 'const nextConfig|headers|Content-Security-Policy')"
			if [ ! -f "${REPO_ROOT%/}/$path" ]; then
				path="frontend/src/app/page.tsx"
				line="$(first_existing_line "$path")"
			fi
			;;
		*"Content Security Policy"*|*"security headers"*|*"Security Headers"*)
			path="frontend/next.config.ts"
			line="$(first_existing_line "$path" 'const nextConfig|headers')"
			;;
		*"JWT"*|*"Authentication"*)
			path="backend/api/auth.py"
			line="$(first_existing_line "$path" 'jwt\.decode|JWT_DECODE_REQUIRED_CLAIMS|_build_oidc_jwks_client')"
			;;
	esac

	if [ -n "$path" ] && [ -f "${REPO_ROOT%/}/$path" ] && [[ "$line" =~ ^[0-9]+$ ]]; then
		printf '%s\t%s\t%s' "$path" "$line" "derived from Strix title: $title"
		return 0
	fi

	printf 'unknown\t1\tStrix report did not include a mappable Code Location'
}

extract_strix_failed_check_block() {
	local source_file="$1"
	local output_file="$2"

	awk '
		/^## Failed check: / {
			in_strix = ($0 ~ /^## Failed check: .*Strix/)
		}
		in_strix { print }
	' "$source_file" >"$output_file"
}

extract_strix_reports() {
	local source_file="$1"
	perl -CS -ne '
		sub clean {
			my ($line) = @_;
			$line =~ s/\r//g;
			$line =~ s/\x1b\[[0-9;?]*[A-Za-z]//g;
			if ($line =~ /│/) {
				$line =~ s/^.*?│[[:space:]]*//;
				$line =~ s/[[:space:]]*│.*$//;
			} else {
				$line =~ s/^.*?[0-9]Z[[:space:]]+//;
			}
			$line =~ s/[[:space:]]+/ /g;
			$line =~ s/^[[:space:]]+|[[:space:]]+$//g;
			return $line;
		}
		sub starts_new_field {
			my ($line) = @_;
			return $line =~ /^(Title|Severity|CVSS Score|CVSS Vector|Target|Endpoint|Method|Description|Impact|Technical Analysis|PoC Description|PoC Code|Code Locations|Remediation)\b/i;
		}
		sub finish_report {
			return unless defined $title && length $title;
			push @reports, {
				model => $report_model,
				title => $title,
				severity => $severity,
				endpoint => $endpoint,
				method => $method,
				target => $target,
				location => $location,
			};
			($report_model, $title, $severity, $endpoint, $method, $target, $location) = ("", "", "", "", "", "", "");
			$in_code_locations = 0;
			$expect_location_value = 0;
		}
		sub finish_window {
			finish_report();
			for my $report (@reports) {
				my $model = $report->{model} || $window_model || $current_model || "unknown-model";
				for my $field ($model, @$report{qw(title severity endpoint method target location)}) {
					$field //= "";
					$field =~ s/\t/ /g;
				}
				print join("\x1f", $model, @$report{qw(title severity endpoint method target location)}), "\n";
			}
			@reports = ();
			$window_model = "";
		}
		my $line = clean($_);
		if ($line =~ /^### Strix vulnerability report window/i) {
			finish_window();
			$in_window = 1;
			if ($line =~ m{(?:model|for model)[[:space:]]+((?:github[-_]models|openai|deepseek|vertex_ai)/[A-Za-z0-9._/-]+)}i) {
				$window_model = $1;
				$current_model = $1;
			}
			next;
		}
		if ($line =~ m{(?:^|[[:space:]])Model[[:space:]]+((?:github[-_]models|openai|deepseek|vertex_ai)/[A-Za-z0-9._/-]+)}i ||
			$line =~ m{Strix run failed for model '\''([^'\'']+)'\''}) {
			$current_model = $1;
			$window_model = $1 if $in_window;
			$report_model = $1 if $in_window && defined $title && length $title;
		}
		next unless $in_window;
		if (defined $continuation_field && length $continuation_field) {
			if (!length $line) {
				$continuation_field = "";
			} elsif (!starts_new_field($line) && $line !~ /^[╭╰─]+/ && $line !~ /^Vulnerability Report$/i) {
				if ($continuation_field eq "title") {
					$title .= " " . $line;
				} elsif ($continuation_field eq "endpoint") {
					$endpoint .= " " . $line;
				} elsif ($continuation_field eq "target") {
					$target .= " " . $line;
				}
				next;
			} else {
				$continuation_field = "";
			}
		}
		if (($in_code_locations || $expect_location_value) &&
			$line =~ m{((?:/workspace/[^[:space:]]+|/tmp/strix-pr-scope\.[^[:space:]]+|backend/[^[:space:]]+|frontend/[^[:space:]]+|\.github/[^[:space:]]+|scripts/[^[:space:]]+):[0-9]+(?:-[0-9]+)?)}i) {
			$location ||= $1;
			$expect_location_value = 0;
			next;
		}
		if ($line =~ /^Title:[[:space:]]+(.+)/i) {
			finish_report();
			$title = $1;
			$report_model = $window_model || "";
			$continuation_field = "title";
			next;
		}
		if ($line =~ /^Severity:[[:space:]]+(CRITICAL|HIGH|MEDIUM|LOW|NONE)\b/i) {
			$severity = uc($1);
			next;
		}
		if ($line =~ /^Endpoint:[[:space:]]+(.+)/i) {
			$endpoint = $1;
			$continuation_field = "endpoint";
			next;
		}
		if ($line =~ /^Method:[[:space:]]+(.+)/i) {
			$method = $1;
			$continuation_field = "";
			next;
		}
		if ($line =~ /^Target:[[:space:]]+(.+)/i) {
			$target = $1;
			$continuation_field = "target";
			next;
		}
		if ($line =~ /^Code Locations\b/i) {
			$in_code_locations = 1;
			next;
		}
		if ($line =~ /^Location[[:space:]]+[0-9]+:[[:space:]]*$/i) {
			$expect_location_value = 1;
			next;
		}
		if ($line =~ /(?:Code[[:space:]]+)?Location(?:s)?(?:[[:space:]]+[0-9]+)?[[:space:]]*:[[:space:]]*(.+?:[0-9]+(?:-[0-9]+)?)/i) {
			$location ||= $1;
			$in_code_locations = 0;
			$expect_location_value = 0;
			next;
		}
		END {
			finish_window();
		}
	' "$source_file"
}

emit_known_missing_string_finding() {
	local evidence_file="$1"
	local needle="$2"
	local title="$3"
	local preferred_path
	local match=""
	local path=""
	local line=""

	if ! grep -Fq -- "$needle" "$evidence_file"; then
		return 0
	fi

	shift 3
	for preferred_path in "$@"; do
		if [ -f "${REPO_ROOT%/}/$preferred_path" ]; then
			match="$(grep -nF -- "$needle" "${REPO_ROOT%/}/$preferred_path" | head -n 1 || true)"
			if [ -n "$match" ]; then
				path="$preferred_path"
				line="${match%%:*}"
				break
			fi
		fi
	done

	finding_index=$((finding_index + 1))
	if [ -n "$path" ] && [ -n "$line" ]; then
		printf '### %s. HIGH %s:%s - %s\n' "$finding_index" "$path" "$line" "$title"
		printf -- '- Problem: Strix failed because the trusted self-test log reported missing "%s".\n' "$needle"
		printf -- '- Root cause: The failed check is executing trusted-base workflow material, so this exact line must exist in the trusted workflow/test contract before the check can pass.\n'
		printf -- '- Fix: Keep or add the current-head line at "%s:%s" so trusted-base Strix/OpenCode evidence contains "%s".\n' "$path" "$line" "$needle"
		printf -- '- Regression test: Keep scripts/ci/test_strix_quick_gate.sh assertions covering this exact string.\n\n'
		printf -- '- Suggested edit: ensure `%s:%s` contains the literal `%s`; if the line was removed from trusted-base material, restore it exactly before approving.\n\n' "$path" "$line" "$needle"
	else
		printf '### %s. HIGH unknown:1 - %s\n' "$finding_index" "$title"
		printf -- '- Problem: Strix failed because the trusted self-test log reported missing "%s".\n' "$needle"
		printf -- '- Root cause: No current-head line containing this exact string was found in the expected workflow/test files.\n'
		printf -- '- Fix: Add the exact string "%s" to the relevant workflow or test contract line.\n' "$needle"
		printf -- '- Regression test: Add a static assertion for this exact string.\n\n'
		printf -- '- Suggested edit: add a concrete source line containing `%s` to the matching workflow or CI test file, then rerun Strix self-tests.\n\n' "$needle"
	fi
}

emit_known_unexpected_string_finding() {
	local evidence_file="$1"
	local needle="$2"
	local title="$3"
	local preferred_path
	local match=""
	local path=""
	local line=""

	if ! grep -Fq -- "unexpected '$needle'" "$evidence_file" &&
		! grep -Fq -- "unexpected \"$needle\"" "$evidence_file"; then
		return 0
	fi

	shift 3
	for preferred_path in "$@"; do
		if [ -f "${REPO_ROOT%/}/$preferred_path" ]; then
			match="$(grep -nF -- "$needle" "${REPO_ROOT%/}/$preferred_path" | head -n 1 || true)"
			if [ -n "$match" ]; then
				path="$preferred_path"
				line="${match%%:*}"
				break
			fi
		fi
	done

	finding_index=$((finding_index + 1))
	if [ -n "$path" ] && [ -n "$line" ]; then
		printf '### %s. HIGH %s:%s - %s\n' "$finding_index" "$path" "$line" "$title"
		printf -- '- Problem: Strix failed because the trusted self-test log reported forbidden "%s" in the required workflow.\n' "$needle"
		printf -- '- Root cause: The required workflow grants a broader GITHUB_TOKEN permission than the smoke-test contract allows; required PR scans must keep status publication on explicit app/secret tokens.\n'
		printf -- '- Fix: Remove or downgrade `%s` at `%s:%s` so the required workflow keeps GITHUB_TOKEN status permissions read-only.\n' "$needle" "$path" "$line"
		printf -- '- Regression test: Keep scripts/ci/strix_required_workflow_smoke.sh and scripts/ci/test_strix_quick_gate.sh asserting that the required Strix workflow does not contain `%s`.\n\n' "$needle"
		printf -- '- Suggested edit: change `%s:%s` from `%s` to `statuses: read`, or remove the permission if no status read is needed.\n\n' "$path" "$line" "$needle"
	else
		printf '### %s. HIGH unknown:1 - %s\n' "$finding_index" "$title"
		printf -- '- Problem: Strix failed because the trusted self-test log reported forbidden "%s", but the current source no longer contains that literal in the expected files.\n' "$needle"
		printf -- '- Root cause: The failed check likely used stale trusted-base workflow material or the evidence did not include a mappable current-head source line.\n'
		printf -- '- Fix: Rerun the current-head Strix check after confirming the workflow and tests no longer contain `%s`.\n' "$needle"
		printf -- '- Regression test: Keep the required workflow smoke test covering this forbidden literal.\n\n'
		printf -- '- Suggested edit: no source edit can be suggested from the current source; rerun after the trusted workflow source updates.\n\n'
	fi
}

all_failed_check_blocks_have_billing_lock() {
	local evidence_file="$1"

	grep -Fqi "account is locked due to a billing issue" "$evidence_file" || return 1
	awk '
		BEGIN {
			has_failed_check = 0
			block_has_billing_lock = 0
			all_blocks_have_billing_lock = 1
		}
		/^## Failed check: / {
			if (has_failed_check && !block_has_billing_lock) {
				all_blocks_have_billing_lock = 0
			}
			has_failed_check = 1
			block_has_billing_lock = 0
			next
		}
		has_failed_check && tolower($0) ~ /account is locked due to a billing issue/ {
			block_has_billing_lock = 1
		}
		END {
			if (has_failed_check && !block_has_billing_lock) {
				all_blocks_have_billing_lock = 0
			}
			if (has_failed_check && all_blocks_have_billing_lock) {
				exit 0
			}
			exit 1
		}
	' "$evidence_file"
}

emit_github_billing_lock_finding() {
	local match=""
	local path=".github/workflows/opencode-review.yml"
	local line="1"

	if ! all_failed_check_blocks_have_billing_lock "$EVIDENCE_FILE"; then
		return 0
	fi

	if [ -f "${REPO_ROOT%/}/$path" ]; then
		match="$(grep -nF -- "account is locked due to a billing issue" "${REPO_ROOT%/}/$path" | head -n 1 || true)"
		if [ -n "$match" ]; then
			line="${match%%:*}"
		fi
	fi

	finding_index=$((finding_index + 1))
	printf '### %s. HIGH %s:%s - GitHub Actions billing lock blocked current-head check evidence\n' "$finding_index" "$path" "$line"
	printf -- '- Problem: Every active failed-check block says the job was not started because the GitHub account is locked due to a billing issue.\n'
	printf -- '- Root cause: GitHub Actions never started the affected jobs, so the evidence is an external CI/account blocker rather than a repository source defect.\n'
	printf -- '- Fix: Restore GitHub billing or Actions access, then rerun the current-head checks; do not request repository source changes from this evidence alone.\n'
	printf -- '- Regression test: Keep the OpenCode approval gate classifying all-billing-lock failed checks as a neutral COMMENT review so stale REQUEST_CHANGES reviews are not created for infrastructure-only failures.\n\n'
	printf -- '- Suggested edit: no repository source edit is appropriate until the billing lock is cleared and a real failed job log or annotation identifies an actionable source line.\n\n'
}

emit_pytest_failure_findings() {
	local evidence_file="$1"
	local clean_file
	local failures_file
	local failure_line
	local failure_spec
	local path
	local test_name
	local test_leaf
	local line
	local term
	local term_match
	local location_line
	local check_label
	local step_label
	local seen_key
	local seen_file

	clean_file="$(mktemp)"
	failures_file="$(mktemp)"
	seen_file="$(mktemp)"
	tmp_files+=("$clean_file" "$failures_file" "$seen_file")
	strip_ansi_file "$evidence_file" >"$clean_file"

	grep -E "FAILED [^[:space:]]+\.py::" "$clean_file" >"$failures_file" || true
	if [ ! -s "$failures_file" ]; then
		return 0
	fi

	check_label="GitHub Check"
	step_label="test step"
	term="$(
		perl -ne 'if (/assert [\x27"]([^\x27"]+)[\x27"] not in/) { print "$1\n"; exit }' "$clean_file"
	)"

	while IFS= read -r failure_line; do
		failure_spec="$(
			printf '%s\n' "$failure_line" |
				sed -E 's/^.*FAILED ([^[:space:]]+\.py::[^[:space:]]+).*/\1/'
		)"
		if [ -z "$failure_spec" ] || [ "$failure_spec" = "$failure_line" ]; then
			continue
		fi
		path="${failure_spec%%::*}"
		test_name="${failure_spec#*::}"
		test_leaf="${test_name##*::}"
		test_leaf="${test_leaf%%[*}"
		seen_key="${path}::${test_name}"
		if grep -Fxq -- "$seen_key" "$seen_file"; then
			continue
		fi
		printf '%s\n' "$seen_key" >>"$seen_file"

		line="$(
			perl -Mstrict -Mwarnings -e '
				my ($path, $file) = @ARGV;
				open my $fh, "<", $file or exit 0;
				while (my $row = <$fh>) {
					if ($row =~ /\Q$path\E:(\d+):/) {
						print "$1\n";
						exit 0;
					}
				}
			' "$path" "$clean_file"
		)"
		if [ -n "$term" ] && [ -f "${REPO_ROOT%/}/$path" ]; then
			term_match="$(grep -nF -- "$term" "${REPO_ROOT%/}/$path" | head -n 1 || true)"
			if [ -n "$term_match" ]; then
				line="${term_match%%:*}"
			fi
		fi
		if [ -z "$line" ] && [ -f "${REPO_ROOT%/}/$path" ]; then
			location_line="$(grep -nE -- "def[[:space:]]+${test_leaf//./\\.}[[:space:]]*\\(" "${REPO_ROOT%/}/$path" | head -n 1 || true)"
			if [ -n "$location_line" ]; then
				line="${location_line%%:*}"
			fi
		fi
		if [ -z "$line" ] || ! [[ "$line" =~ ^[0-9]+$ ]]; then
			line="1"
		fi

		finding_index=$((finding_index + 1))
		printf '### %s. HIGH %s:%s - Failed GitHub Check needs a source-backed pytest fix for %s\n' "$finding_index" "$path" "$line" "$test_name"
		printf -- '- Problem: `%s` failed in `%s`; pytest reported `%s`, so the review must explain the failing assertion instead of linking only to the Actions URL.\n' "$check_label" "$step_label" "$failure_spec"
		if [ -n "$term" ]; then
			printf -- '- Root cause: The failed log says the forbidden literal `%s` is still present in the tested source. The current source line `%s:%s` is the first matching location found for that literal or the failing assertion path.\n' "$term" "$path" "$line"
			printf -- '- Fix: Change `%s:%s` so the test no longer embeds or permits `%s` in the inspected source. For self-inspection harnesses, build sentinel strings without the exact forbidden literal or inspect the target module instead of `Path(__file__)`.\n' "$path" "$line" "$term"
		else
			printf -- '- Root cause: The failed log maps the pytest failure to `%s:%s`; OpenCode must inspect that source line and explain the assertion-level cause before approval.\n' "$path" "$line"
			printf -- '- Fix: Patch `%s:%s` to satisfy `%s`, then rerun the focused pytest target.\n' "$path" "$line" "$test_name"
		fi
		printf -- '- Regression test: Run `cd backend && python -m pytest %s::%s -q` when the repository has a backend test layout, then rerun the failed check.\n' "$path" "$test_name"
		printf -- '- Suggested edit: update `%s:%s` for `%s`; do not approve or post a URL-only review until the exact failing assertion is explained with this file, line, command, and fix direction.\n\n' "$path" "$line" "$test_name"
	done <"$failures_file"
}

emit_cancelled_check_findings() {
	local evidence_file="$1"
	local clean_file
	local cancelled_file
	local check_label
	local annotation

	clean_file="$(mktemp)"
	cancelled_file="$(mktemp)"
	tmp_files+=("$clean_file" "$cancelled_file")
	strip_ansi_file "$evidence_file" >"$clean_file"

	awk '
		/^## Failed check: / {
			check = $0
			sub(/^## Failed check: /, "", check)
			in_cancelled = 0
		}
		/^- Conclusion: .*CANCELLED/ || /^- Conclusion: .*cancelled/ {
			in_cancelled = 1
		}
		in_cancelled && /Canceling since a higher priority waiting request/ {
			print check "\t" $0
		}
	' "$clean_file" >"$cancelled_file"

	while IFS=$'\t' read -r check_label annotation; do
		if [ -z "$check_label" ]; then
			continue
		fi
		printf 'Non-source-backed cancelled check queue state: %s reported %s. Wait for or rerun the newest same-head check; no repository source edit is justified by this cancelled check alone.\n' "$check_label" "$annotation" >&2
	done <"$cancelled_file"
}

emit_strix_report_findings() {
	local strix_evidence_file="$1"
	local reports_file
	local model
	local title
	local severity
	local endpoint
	local method
	local target
	local location
	local mapped
	local path
	local line
	local source_detail

	if ! grep -Eq "^### Strix vulnerability report window([[:space:]]|$)" "$strix_evidence_file"; then
		return 0
	fi

	reports_file="$(mktemp)"
	tmp_files+=("$reports_file")
	extract_strix_reports "$strix_evidence_file" >"$reports_file"

	while IFS=$'\037' read -r model title severity endpoint method target location; do
		if [ -z "$title" ] || [ "$severity" = "NONE" ]; then
			continue
		fi
		mapped="$(derive_location_from_report "$title" "$endpoint" "$target" "$location")"
		IFS=$'\t' read -r path line source_detail <<<"$mapped"
		if [ "$path" = "unknown" ]; then
			printf '%s\t%s\t%s\t%s\n' "$model" "$title" "${severity:-UNKNOWN}" "$source_detail" >>"$unmapped_strix_reports_file"
			continue
		fi

		finding_index=$((finding_index + 1))
		printf '### %s. %s %s:%s - Strix report from %s: %s\n' "$finding_index" "${severity:-HIGH}" "$path" "$line" "$model" "$title"
		printf -- '- Problem: Strix Security Scan failed and %s reported "%s" with severity %s. Endpoint: %s. Method: %s. Code location evidence: %s.\n' "$model" "$title" "${severity:-UNKNOWN}" "${endpoint:-N/A}" "${method:-N/A}" "$source_detail"
		printf -- '- Root cause: The failed Strix evidence contains a distinct model vulnerability report, so OpenCode must not collapse it into provider-quota or generic check-failure text.\n'
		printf -- '- Fix: Inspect and patch %s:%s for this exact report before approval; apply the remediation described by Strix for "%s" and keep the review finding tied to this line.\n' "$path" "$line" "$title"
		printf -- '- Regression test: Add or update coverage that exercises the reported endpoint/path and proves the %s finding cannot recur.\n\n' "${severity:-Strix}"
		printf -- '- Suggested edit: change `%s:%s` for the `%s` report from model `%s`; preserve the exact endpoint `%s`, method `%s`, and Code Location evidence `%s` in the OpenCode review finding.\n\n' "$path" "$line" "$title" "$model" "${endpoint:-N/A}" "${method:-N/A}" "$source_detail"
	done <"$reports_file"
}

emit_strix_provider_failure_finding() {
	local strix_evidence_file="$1"
	local match=""
	local path=".github/workflows/strix.yml"
	local line="1"

	if ! grep -Eq "LLM CONNECTION FAILED|RateLimitError|Too many requests|HTTPStatusError|401 Unauthorized|api\\.deepseek\\.com|Authentication Fails|DeepseekException|budget limit|Configured model and fallback models were unavailable|provider infrastructure|Below-threshold findings detected|Unable to map Strix findings" "$strix_evidence_file"; then
		return 0
	fi

	if [ -f "${REPO_ROOT%/}/$path" ]; then
		match="$(grep -nE -- "^[[:space:]]*STRIX_FALLBACK_MODELS:" "${REPO_ROOT%/}/$path" | head -n 1 || true)"
		if [ -n "$match" ]; then
			line="${match%%:*}"
		fi
	fi

	finding_index=$((finding_index + 1))
	if grep -Eq "^### Strix vulnerability report window([[:space:]]|$)" "$strix_evidence_file"; then
		printf '### %s. HIGH %s:%s - Strix provider signal left current-head security evidence incomplete\n' "$finding_index" "$path" "$line"
		if [ -s "$unmapped_strix_reports_file" ]; then
			printf -- '- Problem: Strix produced one or more vulnerability report windows that did not map to an existing repository file, then the failed log reported provider infrastructure/failure-signal output such as LLM CONNECTION FAILED, RateLimitError, budget-limit, "Below-threshold findings detected", "Unable to map Strix findings", or fallback provider signal. Unmapped reports: '
			awk -F '\t' '{
				printf "%s%s reported \"%s\" (%s; %s)", sep, $1, $2, $3, $4
				sep = "; "
			}' "$unmapped_strix_reports_file"
			printf '.\n'
		else
			printf -- '- Problem: Strix produced one or more vulnerability report windows, then the failed log still reported provider infrastructure/failure-signal output such as LLM CONNECTION FAILED, RateLimitError, budget-limit, "Below-threshold findings detected", "Unable to map Strix findings", or fallback provider signal.\n'
		fi
		printf -- '- Root cause: The scanner evidence is incomplete even after model reports were emitted; unmapped or provider-failed Strix reports are scanner evidence blockers, not source-backed code review findings. OpenCode must not anchor a report to an unrelated workflow line unless the report includes a mappable repository Code Location.\n'
		printf -- '- Fix: Re-run Strix after GitHub Models capacity recovers or run an explicitly configured manual provider evidence scan with valid credentials; keep %s:%s aligned with the approved fallback model list.\n' "$path" "$line"
		printf -- '- Regression test: Keep failed-check evidence and validation covering provider-signal failures after vulnerability reports, including unmapped/nonexistent Code Locations, so partial reports cannot be downgraded to approval or converted into hallucinated source fixes.\n\n'
		printf -- '- Suggested edit: do not change unrelated source lines for unmapped reports; first obtain a clean Strix rerun or a report with a repository Code Location, while keeping `%s:%s` on the approved GitHub Models fallback route.\n\n' "$path" "$line"
	else
		printf '### %s. HIGH %s:%s - Strix provider failure blocked current-head security evidence\n' "$finding_index" "$path" "$line"
		if grep -Eq "api\\.deepseek\\.com|401 Unauthorized|Authentication Fails|DeepseekException" "$strix_evidence_file"; then
			printf -- '- Problem: Strix failed before producing vulnerability reports. The failed log reported `RateLimitError` / `Too many requests` for the primary `openai/gpt-5` attempt, then fallback attempts reached direct DeepSeek (`api.deepseek.com`) and failed with `401 Unauthorized` or `Authentication Fails`, ending with `Configured model and fallback models were unavailable`.\n'
			printf -- '- Root cause: The fallback model names were not routed through the GitHub Models endpoint for this failed PR check, so a GitHub Models token was used against direct DeepSeek instead of `https://models.github.ai/inference`; no Strix Vulnerability Report window was produced.\n'
			printf -- '- Fix: Do not approve from this failed scan. Keep %s:%s on the approved GitHub Models fallback list (`github_models/deepseek/deepseek-v3-0324 github_models/deepseek/deepseek-r1-0528`) and remove direct DeepSeek fallback routing from the workflow before rerunning the failed PR Strix check.\n' "$path" "$line"
			printf -- '- Suggested edit: `%s:%s` must use `STRIX_FALLBACK_MODELS: ${{ steps.gate.outputs.provider_mode == '\''github_models'\'' && '\''github_models/deepseek/deepseek-v3-0324 github_models/deepseek/deepseek-r1-0528'\'' || '\'''\'' }}` instead of unqualified `deepseek/...` values that route to `api.deepseek.com`.\n' "$path" "$line"
		else
			printf -- '- Problem: Strix failed before producing vulnerability reports. The failed log reported LLM CONNECTION FAILED, RateLimitError or Too many requests for the primary model, provider/budget output for fallback models, and Configured model and fallback models were unavailable.\n'
			printf -- '- Root cause: The configured GitHub Models primary/fallback provider capacity or provider route failed for this run; no Strix Vulnerability Report window was produced, so there is no application source line to patch from this evidence.\n'
			printf -- '- Fix: Do not approve from this failed scan. Re-run Strix after GitHub Models capacity recovers or run an explicitly configured manual provider evidence scan with valid credentials; keep the configured fallback line at %s:%s aligned with the approved model list.\n' "$path" "$line"
			printf -- '- Suggested edit: keep `%s:%s` on the approved GitHub Models fallback list and rerun the current-head Strix check; there is no application source patch until Strix emits a vulnerability Code Location.\n' "$path" "$line"
		fi
		printf -- '- Regression test: Keep the failed-check evidence collector preserving RateLimitError, budget-limit, provider infrastructure, and unavailable-model lines so OpenCode reviews can distinguish external provider blockers from code vulnerabilities.\n\n'
	fi
}

emit_strix_cancelled_without_log_finding() {
	local strix_evidence_file="$1"
	local match=""
	local path=".github/workflows/strix.yml"
	local line="1"

	if ! grep -Fq "Conclusion:" "$strix_evidence_file" ||
		! grep -Fq "cancelled" "$strix_evidence_file" ||
		! grep -Fq "No GitHub Actions job log is available for this failed workflow run." "$strix_evidence_file"; then
		return 0
	fi

	if [ -f "${REPO_ROOT%/}/$path" ]; then
		match="$(
			grep -nF -- "cancel-in-progress: \${{ github.event_name == 'pull_request_target' && github.event.action == 'closed' }}" "${REPO_ROOT%/}/$path" |
				head -n 1 || true
		)"
		if [ -z "$match" ]; then
			match="$(grep -nF -- "cancel-in-progress: false" "${REPO_ROOT%/}/$path" | head -n 1 || true)"
		fi
		if [ -z "$match" ]; then
			match="$(grep -nF -- "cancel-in-progress: true" "${REPO_ROOT%/}/$path" | head -n 1 || true)"
		fi
		if [ -n "$match" ]; then
			line="${match%%:*}"
		fi
	fi

	finding_index=$((finding_index + 1))
	printf '### %s. HIGH %s:%s - Current-head Strix evidence is missing because the workflow run was cancelled before logs\n' "$finding_index" "$path" "$line"
	printf -- '- Problem: Strix Security Scan reported a current-head workflow_run conclusion of cancelled, but GitHub emitted no failed job log and no Strix Vulnerability Report window.\n'
	if pr_changes_trusted_strix_inputs; then
		printf -- '- Root cause: The security gate has no usable Strix evidence for this head SHA. This PR changes trusted Strix workflow or gate inputs, but the cancelled pull_request_target run still used the base branch copies, so current-head edits cannot affect this run.\n'
		printf -- '- Fix: Do not invent an application code fix from this cancelled run. Re-run Strix after the trusted base branch contains the workflow/gate change or capture equivalent temporary evidence tied to this head SHA; keep the workflow concurrency line at %s:%s aligned with the intended queue isolation.\n' "$path" "$line"
		printf -- '- Regression test: Keep failed-check evidence collection explicit for cancelled workflow runs with no job log and cover self-modifying Strix workflow PRs so reviews explain trusted-base execution semantics.\n\n'
	else
		printf -- '- Root cause: The security gate has no usable Strix evidence for this head SHA. This is a workflow execution/queue state, not an application vulnerability finding, so OpenCode must not invent a source-code fix.\n'
		printf -- '- Fix: Do not approve from this cancelled run. Re-run the current-head Strix Security Scan after stale runs complete or are cancelled, then review the resulting job log; keep the workflow concurrency line at %s:%s so stale runs do not silently replace current-head evidence.\n' "$path" "$line"
		printf -- '- Regression test: Keep failed-check evidence collection explicit for cancelled workflow runs with no job log so reviewers see that the blocker is missing scanner evidence.\n\n'
	fi
	printf -- '- Suggested edit: preserve `%s:%s` with event-separated Strix concurrency, so workflow_dispatch evidence cannot cancel the required pull_request_target context while same-event stale runs still collapse to current-head evidence; rerun current-head Strix until logs exist.\n\n' "$path" "$line"
}

extract_supply_chain_records() {
	# Parse the failed-check EVIDENCE for supply-chain scanner results
	# (osv-scanner, trivy-fs, dependency-review) and emit one record per
	# distinct vulnerability. Fields are joined with the ASCII Unit Separator
	# (\x1f), not a tab, so empty interior fields (e.g. a missing installed or
	# fixed version) survive read-back without shifting later columns. Supply-chain findings are source-backed because the
	# scanners name the exact vulnerable package, its manifest file, the
	# CVE/GHSA advisory id, and the fixed version. Two evidence shapes are
	# recognized inside a supply-chain failed-check block:
	#
	#   1. Canonical structured line (emitted by the failed-check evidence
	#      collector after it normalizes osv/trivy/dependency-review SARIF and
	#      dependency-review summaries):
	#        - Supply-chain vulnerability: id=CVE-2023-32681 severity=HIGH \
	#          package=requests installed=2.19.0 fixed=2.31.0 manifest=requirements.txt
	#   2. A Trivy filesystem findings table logged to the job log, grouped by a
	#      manifest header such as "requirements.txt (pip)".
	#
	# Record columns (\x1f-separated): manifest, package, installed, fixed, id, severity, evidence, label, line_hint
	local source_file="$1"

	perl -CS -ne '
		BEGIN { our (%seen, $in_block, $manifest, $label); $in_block = 0; }
		sub trim { my ($s) = @_; $s =~ s/^\s+//; $s =~ s/\s+$//; return $s; }
		sub is_manifest {
			my ($p) = @_;
			my $base = $p; $base =~ s#.*/##;
			return 1 if $base =~ /^(Cargo\.(lock|toml)|uv\.lock|poetry\.lock|Pipfile(\.lock)?|pyproject\.toml|package(-lock)?\.json|yarn\.lock|pnpm-lock\.yaml|go\.(mod|sum)|Gemfile(\.lock)?|composer(\.lock|\.json)|Package\.resolved|Package\.swift|mix\.lock|pubspec\.(yaml|lock)|gradle\.lockfile|conda-lock\.yml)$/i;
			return 1 if $base =~ /^requirements[\w.-]*\.(txt|in)$/i;
			return 0;
		}
		sub emit {
			my ($m,$p,$inst,$fix,$id,$sev,$ev,$lab,$hint) = @_;
			return unless length $id && length $p && length $m;
			$hint = "" unless defined $hint && $hint =~ /^[0-9]+$/ && $hint > 0;
			my $key = lc("$m|$p|$id");
			return if $seen{$key}++;
			for my $f ($m,$p,$inst,$fix,$id,$sev,$ev,$lab,$hint) { $f //= ""; $f =~ s/[\x1f\r\n]/ /g; }
			print join("\x1f", $m,$p,$inst,$fix,$id,$sev,$ev,$lab,$hint), "\n";
		}
		my $line = $_;
		$line =~ s/\r//g;
		$line =~ s/\x1b\[[0-9;?]*[A-Za-z]//g;
		if ($line =~ /^## Failed check:\s*(.+?)\s*$/) {
			$label = $1;
			$in_block = ($label =~ /osv|trivy|dependency[ _-]?review/i) ? 1 : 0;
			$manifest = "";
			next;
		}
		# A new non-supply-chain section header ends any manifest context.
		next unless $in_block;
		my $clean = trim($line);

		# Shape 1: canonical structured supply-chain line (order-independent).
		if ($clean =~ /Supply-chain vulnerability:/i) {
			my %kv;
			while ($clean =~ /(\w+)=([^\s|]+)/g) { $kv{lc $1} = $2; }
			my $id = $kv{id} // $kv{vuln} // $kv{cve} // $kv{ghsa} // "";
			my $pkg = $kv{package} // $kv{pkg} // $kv{library} // "";
			my $man = $kv{manifest} // $kv{file} // $kv{path} // "";
			my $inst = $kv{installed} // $kv{version} // "";
			my $fix = $kv{fixed} // $kv{patched} // "";
			my $sev = uc($kv{severity} // "HIGH");
			my $hint = $kv{line} // "";
			emit($man,$pkg,$inst,$fix,$id,$sev,$clean,$label,$hint);
			next;
		}

		# Track a Trivy manifest header such as "requirements.txt (pip)".
		if ($clean =~ m{^([\w./\-]+?)\s+\(([\w.\-]+)\)\s*$}) {
			$manifest = $1 if is_manifest($1);
			next;
		}

		# Shape 2: Trivy findings table row. Cells are separated by the box
		# drawing bar; the vulnerability id occupies its own cell.
		if ($clean =~ /[\x{2502}|]/ &&
			$clean =~ /(CVE-\d{4}-\d{3,}|GHSA-[0-9a-z]{4}-[0-9a-z]{4}-[0-9a-z]{4})/i) {
			my @cells = map { trim($_) } split /[\x{2502}|]/, $clean;
			@cells = grep { length } @cells;
			my ($idx) = grep {
				$cells[$_] =~ /^(CVE-\d{4}-\d{3,}|GHSA-[0-9a-z]{4}-[0-9a-z]{4}-[0-9a-z]{4})$/i
			} 0 .. $#cells;
			next unless defined $idx;
			my $id = $cells[$idx];
			my $pkg = ($idx >= 1) ? $cells[$idx - 1] : "";
			my $man = $manifest;
			for my $c (@cells) { if (is_manifest($c)) { $man = $c; last; } }
			my $sev = "HIGH";
			my @after = @cells[$idx + 1 .. $#cells];
			for my $c (@after) { if ($c =~ /^(CRITICAL|HIGH|MEDIUM|LOW)$/i) { $sev = uc $c; last; } }
			my @vers = grep { /^v?\d[\w.\-+]*$/ } @after;
			my $inst = @vers ? $vers[0] : "";
			my $fix = (@vers > 1) ? $vers[1] : "";
			emit($man,$pkg,$inst,$fix,$id,$sev,$clean,$label,"");
			next;
		}
	' <"$source_file"
}

emit_supply_chain_findings() {
	local evidence_file="$1"
	local records_file
	local manifest package installed fixed vuln_id severity evidence_line check_label line_hint
	local resolved base found matches best line pin_line_text
	local source suggested_line

	records_file="$(mktemp)"
	tmp_files+=("$records_file")
	extract_supply_chain_records "$evidence_file" >"$records_file"
	if [ ! -s "$records_file" ]; then
		return 0
	fi

	# Records are joined with the ASCII Unit Separator (\x1f), NOT a tab. Tab is an
	# IFS-whitespace character, so `read` would collapse consecutive tabs and shift
	# every column left whenever an interior field (e.g. installed or fixed) is
	# empty. \x1f is not IFS-whitespace, so empty interior fields are preserved
	# positionally and each value lands in its correct column.
	while IFS=$'\x1f' read -r manifest package installed fixed vuln_id severity evidence_line check_label line_hint; do
		if [ -z "$vuln_id" ] || [ -z "$package" ] || [ -z "$manifest" ]; then
			continue
		fi

		case "$(printf '%s' "$check_label" | tr '[:upper:]' '[:lower:]')" in
			*trivy*) source="trivy" ;;
			*osv*) source="osv-scanner" ;;
			*dependency*) source="dependency-review" ;;
			*) source="supply-chain scanner" ;;
		esac

		# Resolve the manifest under the checked-out repository root. The scanner
		# names a repo-relative path; if that path is absent (path was reported
		# relative to a scan subdirectory) fall back to the basename.
		resolved="$manifest"
		if [ ! -f "${REPO_ROOT%/}/$resolved" ]; then
			base="${manifest##*/}"
			found="$(cd "${REPO_ROOT%/}" 2>/dev/null && git ls-files -- "**/$base" "$base" 2>/dev/null | head -n 1 || true)"
			if [ -z "$found" ]; then
				found="$(cd "${REPO_ROOT%/}" 2>/dev/null && find . -name "$base" -not -path '*/.git/*' 2>/dev/null | sed 's#^\./##' | head -n 1 || true)"
			fi
			if [ -n "$found" ]; then
				resolved="$found"
			fi
		fi

		# Locate the exact manifest line that pins the vulnerable package. Never
		# emit line 0; default to line 1 while still citing the scanner evidence.
		line="1"
		pin_line_text=""
		if [ -f "${REPO_ROOT%/}/$resolved" ]; then
			matches="$(grep -niF -- "$package" "${REPO_ROOT%/}/$resolved" 2>/dev/null || true)"
			if [ -n "$matches" ] && [ -n "$installed" ]; then
				best="$(printf '%s\n' "$matches" | grep -F -- "$installed" | head -n 1 || true)"
			else
				best=""
			fi
			if [ -z "$best" ]; then
				best="$(printf '%s\n' "$matches" | head -n 1 || true)"
			fi
			if [ -n "$best" ]; then
				line="${best%%:*}"
				pin_line_text="${best#*:}"
			elif [[ "$line_hint" =~ ^[0-9]+$ ]] && [ "$line_hint" -ge 1 ]; then
				# Package name was not grep-locatable in the manifest (common for
				# transitive lockfile entries); trust the scanner-provided line
				# from the SARIF location instead of falling back to line 1.
				line="$line_hint"
			fi
		elif [[ "$line_hint" =~ ^[0-9]+$ ]] && [ "$line_hint" -ge 1 ]; then
			line="$line_hint"
		fi
		if ! [[ "$line" =~ ^[0-9]+$ ]] || [ "$line" -lt 1 ]; then
			line="1"
		fi

		# Build a GitHub-suggestion-ready diff when the pin line is a simple
		# version pin that contains the installed version literally.
		suggested_line=""
		if [ -n "$pin_line_text" ] && [ -n "$installed" ] && [ -n "$fixed" ] &&
			printf '%s' "$pin_line_text" | grep -Fq -- "$installed"; then
			suggested_line="$(INSTALLED="$installed" FIXED="$fixed" perl -pe 's/\Q$ENV{INSTALLED}\E/$ENV{FIXED}/g' <<<"$pin_line_text")"
			if [ "$suggested_line" = "$pin_line_text" ]; then
				suggested_line=""
			fi
		fi

		finding_index=$((finding_index + 1))
		printf '### %s. %s %s:%s - Supply-chain vulnerability %s in %s\n' "$finding_index" "${severity:-HIGH}" "$resolved" "$line" "$vuln_id" "$package"
		printf -- '- Problem: The failed check `%s` reported a supply-chain vulnerability: `%s` affects `%s` %s. Scanner evidence: `%s`.\n' "$check_label" "$vuln_id" "$package" "${installed:-(version reported by scanner)}" "$evidence_line"
		printf -- '- Root cause: `%s:%s` pins `%s` at %s, which the %s scan flags as vulnerable under `%s` (severity %s). This is a supply-chain/dependency vulnerability, not a scanner infrastructure failure, so it must be fixed in the manifest.\n' "$resolved" "$line" "$package" "${installed:-the affected version}" "$source" "$vuln_id" "${severity:-HIGH}"
		# The upgrade target must always be a version (or an instruction), never a
		# CVE/GHSA id. Phrase the fix around which of installed/fixed we actually
		# have so a missing version never produces a broken sentence.
		if [ -n "$fixed" ] && [ -n "$installed" ]; then
			printf -- '- Fix: bump `%s` from %s to %s in `%s:%s`, regenerate the lockfile if applicable, then rerun the failed `%s` scan.\n' "$package" "$installed" "$fixed" "$resolved" "$line" "$check_label"
		elif [ -n "$fixed" ]; then
			printf -- '- Fix: upgrade `%s` to %s in `%s:%s`, regenerate the lockfile if applicable, then rerun the failed `%s` scan.\n' "$package" "$fixed" "$resolved" "$line" "$check_label"
		else
			printf -- '- Fix: no fixed version is available upstream for `%s` %s; remove or replace the dependency, or pin to a patched fork, in `%s:%s`, then rerun the failed `%s` scan.\n' "$package" "${installed:-(version reported by scanner)}" "$resolved" "$line" "$check_label"
		fi
		printf -- '- Regression test: after bumping, rerun the %s scan (osv-scanner / trivy-fs / dependency-review) on the PR head and confirm `%s` for `%s` no longer appears; keep the non-vulnerable version pinned so the advisory cannot regress.\n' "$source" "$vuln_id" "$package"
		if [ -n "$suggested_line" ]; then
			printf -- '- Suggested edit: apply this GitHub suggestion on `%s:%s`:\n\n```suggestion\n%s\n```\n\n' "$resolved" "$line" "$suggested_line"
		elif [ -n "$fixed" ]; then
			printf -- '- Suggested edit: update `%s:%s` so `%s` requires `%s` or later.\n\n' "$resolved" "$line" "$package" "$fixed"
		else
			printf -- '- Suggested edit: update `%s:%s` so `%s` requires the first non-vulnerable release for `%s`.\n\n' "$resolved" "$line" "$package" "$vuln_id"
		fi
	done <"$records_file"
}

strix_evidence_file="$(mktemp)"
tmp_files+=("$strix_evidence_file")
extract_strix_failed_check_block "$EVIDENCE_FILE" "$strix_evidence_file"

emit_known_missing_string_finding \
	"$EVIDENCE_FILE" \
	"steps.target_visibility.outputs.is_private == 'false' && 'nvidia_nim/nvidia/nemotron-3-super-120b-a12b' || 'gpt-5.4'" \
	"Strix public scans must default to NVIDIA NIM while private scans retain the contracted provider" \
	".github/workflows/strix.yml" \
	"scripts/ci/test_strix_quick_gate.sh"
emit_known_missing_string_finding \
	"$EVIDENCE_FILE" \
	"STRIX_LLM must select NVIDIA NIM Nemotron, GitHub Models openai/gpt-5 or newer, direct OpenAI GPT-5.4 or newer, OpenRouter openrouter/free, or an approved organization Vertex AI model" \
	"Strix unsupported-model errors must name the allowed providers" \
	".github/workflows/strix.yml" \
	"scripts/ci/test_strix_quick_gate.sh"
emit_known_missing_string_finding \
	"$EVIDENCE_FILE" \
	"MODEL: github-models/openai/gpt-5" \
	"OpenCode review must try GitHub Models GPT-5 first" \
	".github/workflows/opencode-review.yml" \
	"scripts/ci/test_strix_quick_gate.sh"
emit_known_unexpected_string_finding \
	"$EVIDENCE_FILE" \
	"statuses: write" \
	"Strix required workflow must keep GITHUB_TOKEN statuses read-only" \
	".github/workflows/strix.yml" \
	"scripts/ci/test_strix_quick_gate.sh" \
	"scripts/ci/strix_required_workflow_smoke.sh"

emit_github_billing_lock_finding
emit_pytest_failure_findings "$EVIDENCE_FILE"
emit_supply_chain_findings "$EVIDENCE_FILE"
emit_cancelled_check_findings "$EVIDENCE_FILE"
emit_strix_report_findings "$strix_evidence_file"
emit_strix_provider_failure_finding "$strix_evidence_file"
emit_strix_cancelled_without_log_finding "$strix_evidence_file"

if [ "$finding_index" -eq 0 ]; then
	printf 'No source-backed failed-check fallback finding matched the available evidence. No PR review was posted; retry after current-head failed-check logs or annotations are available, or rerun the failed check to collect them.\n' >&2
	exit 1
fi
