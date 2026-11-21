#!/bin/sh
# Toy "container" for tests and examples: a POSIX shell script standing in for an image.
#   copy DEST FILE...   copy files into DEST (created)
#   mark FILE...        append a line to each file, in place
#   check DIR           fail when a file name under DIR contains "bad"
#   summary DIR         print the number of files under DIR
set -e
op=$1; shift
case "$op" in
  copy) dest=$1; shift; mkdir -p "$dest"; for f in "$@"; do cp -L "$f" "$dest/"; done ;;
  mark) for f in "$@"; do echo "marked" >> "$f"; done ;;
  check) if find "$1" -name '*bad*' -not -path '*/.git/*' | grep -q .; then
           echo "invalid file names" >&2; exit 1; fi ;;
  summary) find "$1" -type f -not -path '*/.git/*' | wc -l ;;
  *) echo "unknown operation $op" >&2; exit 2 ;;
esac
