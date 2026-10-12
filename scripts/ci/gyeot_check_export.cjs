#!/usr/bin/env node
const fs = require('node:fs');
const path = require('node:path');

function plain_record(record_data) {
  return record_data !== null && typeof record_data === 'object' && !Array.isArray(record_data);
}

function verify_export(output_directory, target_platform, private_export_directory) {
  if (!['android', 'ios'].includes(target_platform)) throw new Error('Unsupported native platform.');
  if (typeof private_export_directory !== 'string' || !path.isAbsolute(private_export_directory)) {
    throw new Error('Private export root is required.');
  }
  const private_root = path.resolve(private_export_directory);
  const private_stat = fs.lstatSync(private_root);
  if (private_stat.isSymbolicLink() || !private_stat.isDirectory()) {
    throw new Error('Private export root must be a real directory.');
  }
  const expected_output = path.join(private_root, target_platform);
  if (typeof output_directory !== 'string' || path.resolve(output_directory) !== expected_output) {
    throw new Error('Platform export root must be the owned platform directory.');
  }
  const output_stat = fs.lstatSync(expected_output);
  if (output_stat.isSymbolicLink() || !output_stat.isDirectory()) {
    throw new Error('Platform export root must be a real directory.');
  }
  const output_root = fs.realpathSync(expected_output);
  if (output_root !== path.join(fs.realpathSync(private_root), target_platform)) {
    throw new Error('Platform export root escapes private export root.');
  }
  function verify_reference(reference_path) {
    if (typeof reference_path !== 'string' || !reference_path || reference_path.includes('\0') ||
        reference_path.includes('\\') || path.posix.isAbsolute(reference_path) || path.win32.isAbsolute(reference_path) ||
        reference_path.split('/').some(path_part => ['..', '.', ''].includes(path_part))) {
      throw new Error('Invalid export reference path.');
    }
    const resolved_path = fs.realpathSync(path.join(output_root, reference_path));
    const relative_path = path.relative(output_root, resolved_path);
    if (!relative_path || relative_path === '..' || relative_path.startsWith(`..${path.sep}`) || path.isAbsolute(relative_path)) {
      throw new Error('Export reference escapes output directory.');
    }
    const reference_stat = fs.statSync(resolved_path);
    if (!reference_stat.isFile() || reference_stat.size === 0) throw new Error('Export reference is not a nonempty file.');
    return resolved_path;
  }
  const metadata_data = JSON.parse(fs.readFileSync(verify_reference('metadata.json'), 'utf8'));
  // Installed Expo CLI createMetadataJson producer: version 0 / metro / native bundle + asset list.
  if (!plain_record(metadata_data) || metadata_data.version !== 0 || metadata_data.bundler !== 'metro' ||
      !plain_record(metadata_data.fileMetadata) || !Object.hasOwn(metadata_data.fileMetadata, target_platform)) {
    throw new Error('Invalid native export metadata.');
  }
  for (const [platform_name, platform_data] of Object.entries(metadata_data.fileMetadata)) {
    if (!['android', 'ios'].includes(platform_name) || !plain_record(platform_data) || !Array.isArray(platform_data.assets)) {
      throw new Error('Invalid native platform metadata.');
    }
    if (typeof platform_data.bundle !== 'string' || !/\.(?:js|hbc)$/.test(platform_data.bundle)) {
      throw new Error('Missing native JavaScript bundle reference.');
    }
    verify_reference(platform_data.bundle);
    for (const asset_data of platform_data.assets) {
      if (!plain_record(asset_data) || typeof asset_data.ext !== 'string' || !asset_data.ext) {
        throw new Error('Invalid native asset metadata.');
      }
      verify_reference(asset_data.path);
    }
  }
}

try {
  verify_export(process.argv[2], process.argv[3], process.argv[4]);
} catch (error_data) {
  console.error(`Export postcondition failed: ${error_data.message}`);
  process.exitCode = 1;
}
