#!/usr/bin/env python3
"""
LEDSpicer Configuration Converter 1.0 → 1.1

Changes:
1. version="1.0" → version="1.1"
2. backgroundColor="Black" → backgroundColor="Off"
3. Reader inputs: Remove <listenEvents> tree (source already in <maps>)
4. Normal inputs: Wrap loose <map> elements in <maps>
5. direction ForwardBouncing/BackwardBouncing → Forward/Backward + bouncer="True"
6. Profiles: Convert <startTransitions>/<endTransitions> to <transition>
"""

import os
import sys
import re
import argparse
import shutil
from pathlib import Path
from datetime import datetime


# Reader input types that need maps grouping
READER_TYPES = {"Actions", "Credits", "Impulse", "Blinker"}


def backup_file(filepath: Path, backup_dir: Path) -> None:
	"""Create a backup of the original file."""
	relative   = filepath.relative_to(filepath.anchor) if filepath.is_absolute() else filepath
	backup_path = backup_dir / relative
	backup_path.parent.mkdir(parents=True, exist_ok=True)
	shutil.copy2(filepath, backup_path)


def convert_version(content: str) -> str:
	"""Convert LEDSpicer version="1.0" to version="1.1" (not XML declaration)."""
	# Only convert version in LEDSpicer element, not XML declaration
	# Match version attribute within LEDSpicer tag while preserving whitespace
	def replace_version(match):
		return match.group(0).replace('version="1.0"', 'version="1.1"').replace("version='1.0'", "version='1.1'")

	return re.sub(
		r'<LEDSpicer\s[^>]*version\s*=\s*["\']1\.0["\'][^>]*>',
		replace_version,
		content,
		flags=re.DOTALL
	)


def convert_background_color(content: str) -> str:
	"""Convert backgroundColor="Black" to backgroundColor="Off"."""
	return re.sub(r'backgroundColor\s*=\s*"Black"', 'backgroundColor="Off"', content)


def convert_direction(content: str) -> str:
	"""
	Convert ForwardBouncing/BackwardBouncing to Forward/Backward with bouncer="True".
	Handles both single and double quoted attributes.
	Preserves formatting by adding bouncer on new line if direction was on its own line.
	"""
	def replace_direction(match):
		quote      = match.group(2)
		direction  = match.group(3)
		base_dir   = "Forward" if direction == "ForwardBouncing" else "Backward"
		# Check if there's a newline/tab prefix (attribute on its own line)
		prefix = match.group(1)
		if '\n' in prefix or '\t' in prefix:
			# Preserve indentation for bouncer
			indent = re.search(r'(\n[\t ]+)$', prefix)
			if indent:
				return f'{prefix}direction={quote}{base_dir}{quote}{indent.group(1)}bouncer={quote}True{quote}'
		return f'{prefix}direction={quote}{base_dir}{quote} bouncer={quote}True{quote}'

	return re.sub(
		r'([\s]*)direction\s*=\s*(["\'])(ForwardBouncing|BackwardBouncing)\2',
		replace_direction,
		content
	)


def is_reader_input(content: str) -> bool:
	"""Check if this is a reader-type input file."""
	# Match name attribute in LEDSpicer root element
	match = re.search(r'<LEDSpicer[^>]*\sname\s*=\s*["\'](\w+)["\']', content)
	if match:
		return match.group(1) in READER_TYPES
	return False


def get_input_type(content: str) -> str:
	"""Get the type attribute from LEDSpicer root."""
	match = re.search(r'<LEDSpicer[^>]*\stype\s*=\s*["\'](\w+)["\']', content)
	return match.group(1) if match else ""


def remove_listenevents_element(content: str) -> str:
	"""Remove <listenEvents>...</listenEvents> element tree with <listenEvent> children."""
	# Match listenEvents element with any content
	content = re.sub(r'\s*<listenEvents\s*/>', '', content)
	content = re.sub(r'\s*<listenEvents[^>]*>.*?</listenEvents>', '', content, flags=re.DOTALL)
	return content


def convert_transitions(content: str) -> str:
	"""
	Convert old transition format to new format.

	Old format:
	<startTransitions showElementTimer="3000">
		<animation name="fadeInOut" />
	</startTransitions>
	<endTransitions hideElementTimer="3000">
		<animation name="fadeInOut"/>
	</endTransitions>

	New format:
	<transition
		name="FadeOutIn"
		speed="Normal"
		color="Off"
	/>

	Note: This is a simplified conversion. Complex transitions may need manual review.
	"""
	has_old_transitions = '<startTransitions' in content or '<endTransitions' in content

	if not has_old_transitions:
		return content

	print("  Note: Converting old transition format. Manual review recommended.")

	# Extract any useful info from old format
	speed = "Normal"
	color = "Off"

	# Try to detect animation name to map to transition effect
	anim_match = re.search(r'<animation\s+name\s*=\s*["\']([^"\']+)["\']', content)
	effect     = "FadeOutIn"  # Default
	if anim_match:
		anim_name = anim_match.group(1).lower()
		if 'fade' in anim_name:
			effect = "FadeOutIn"
		elif 'cross' in anim_name:
			effect = "Crossfade"
		elif 'curtain' in anim_name:
			effect = "Curtain"

	# Remove old transition elements
	content = re.sub(r'\s*<startTransitions[^>]*>.*?</startTransitions>', '', content, flags=re.DOTALL)
	content = re.sub(r'\s*<endTransitions[^>]*>.*?</endTransitions>', '', content, flags=re.DOTALL)

	# Add new transition element after the root opening tag
	transition_elem = f'\n\t<transition\n\t\tname="{effect}"\n\t\tspeed="{speed}"\n\t\tcolor="{color}"\n\t/>'

	# Insert after LEDSpicer opening tag
	content = re.sub(
		r'(<LEDSpicer[^>]*>)',
		r'\1' + transition_elem,
		content
	)

	return content


def convert_input_maps(content: str) -> str:
	"""
	Convert old input format to new maps-grouped format.

	Reader types (Actions, Credits, Impulse, Blinker):
	- Already have <maps source="..."> structure
	- Just remove <listenEvents> tree

	Normal input types (Mame, Network):
	- Move loose <map> elements inside a <maps> wrapper
	"""
	if is_reader_input(content):
		# Reader input: just remove <listenEvents> element tree
		return remove_listenevents_element(content)

	# Non-reader inputs: wrap loose <map> elements in <maps>
	if '<map' in content and '<maps' not in content:
		# Find all map elements (self-closing or with content)
		maps_pattern = r'(\t*<map\s[^>]*/\s*>|\t*<map\s[^>]*>.*?</map>)'
		maps         = re.findall(maps_pattern, content, re.DOTALL)
		if maps:
			# Remove old maps and surrounding whitespace
			content = re.sub(r'\s*' + maps_pattern, '', content, flags=re.DOTALL)
			# Create new maps section with proper formatting
			formatted_maps = '\n'.join('\t\t' + m.strip() for m in maps)
			maps_content   = f'\n\t<maps>\n{formatted_maps}\n\t</maps>\n'
			# Insert before </LEDSpicer>
			content = re.sub(r'\s*</LEDSpicer>', maps_content + '</LEDSpicer>', content)

	return content


def convert_file(filepath: Path, dry_run: bool = False, backup_dir: Path = None) -> bool:
	"""
	Convert a single XML file from 1.0 to 1.1 format.
	Returns True if changes were made.
	"""
	try:
		with open(filepath, 'r', encoding='utf-8') as f:
			original = f.read()
	except Exception as e:
		print(f"  Error reading {filepath}: {e}")
		return False

	# Skip non-LEDSpicer files
	if '<LEDSpicer' not in original:
		return False

	# Skip already converted files
	if 'version="1.1"' in original:
		print(f"  {filepath} - Already version 1.1, skipping")
		return False

	# Skip if not version 1.0
	if 'version="1.0"' not in original:
		print(f"  {filepath} - No version 1.0 found, skipping")
		return False

	content = original

	# Apply conversions
	content = convert_version(content)
	content = convert_background_color(content)
	content = convert_direction(content)

	# Convert input maps if this is an Input file
	if get_input_type(content) == "Input":
		content = convert_input_maps(content)

	# Convert transitions if this is a Profile file
	if get_input_type(content) == "Profile":
		content = convert_transitions(content)

	# Check if changes were made
	if content == original:
		print(f"  {filepath} - No changes needed")
		return False

	if dry_run:
		print(f"  {filepath} - Would be converted (dry run)")
		return True

	# Backup original
	if backup_dir:
		backup_file(filepath, backup_dir)

	# Write converted content
	try:
		with open(filepath, 'w', encoding='utf-8') as f:
			f.write(content)
		print(f"  {filepath} - Converted successfully")
		return True
	except Exception as e:
		print(f"  Error writing {filepath}: {e}")
		return False


def find_xml_files(directory: Path) -> list:
	"""Find all XML files in directory recursively."""
	return list(directory.rglob("*.xml"))


def main():
	parser = argparse.ArgumentParser(
		description="Convert LEDSpicer configuration files from 1.0 to 1.1 format"
	)
	parser.add_argument(
		"path",
		type=Path,
		help="File or directory to convert"
	)
	parser.add_argument(
		"-n", "--dry-run",
		action="store_true",
		help="Show what would be converted without making changes"
	)
	parser.add_argument(
		"-b", "--backup",
		type=Path,
		default=None,
		help="Backup directory (default: <path>_backup_<timestamp>)"
	)
	parser.add_argument(
		"--no-backup",
		action="store_true",
		help="Skip creating backups"
	)

	args = parser.parse_args()

	if not args.path.exists():
		print(f"Error: {args.path} does not exist")
		sys.exit(1)

	# Setup backup directory
	backup_dir = None
	if not args.no_backup and not args.dry_run:
		if args.backup:
			backup_dir = args.backup
		else:
			timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
			backup_dir = args.path.parent / f"{args.path.name}_backup_{timestamp}"
		print(f"Backups will be stored in: {backup_dir}")

	# Find files to convert
	if args.path.is_file():
		files = [args.path]
	else:
		files = find_xml_files(args.path)

	if not files:
		print("No XML files found")
		sys.exit(0)

	print(f"Found {len(files)} XML file(s)")
	print()

	converted = 0
	for filepath in files:
		if convert_file(filepath, args.dry_run, backup_dir):
			converted += 1

	print()
	print(f"Conversion complete: {converted} file(s) {'would be ' if args.dry_run else ''}converted")


if __name__ == "__main__":
	main()
