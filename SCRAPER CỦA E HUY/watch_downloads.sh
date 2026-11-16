#!/bin/bash
# Theo dõi Downloads: file lazada_chitiet_*.json mới -> chuyển vào data/raw/details_dom và gộp vào CSV.
export PYTHONIOENCODING=utf-8
DL="/c/Users/ADMIN/Downloads"
DST="/c/Users/Public/Documents/UIT/UIT/DS111/DoAn_DS111/data/raw/details_dom"
SCR="/c/Users/Public/Documents/UIT/UIT/DS111/DoAn_DS111/scraper"
while true; do
  for f in "$DL"/lazada_chitiet_*.json; do
    [ -e "$f" ] || continue
    sleep 3  # đợi Chrome ghi xong
    name=$(basename "$f")
    mv "$f" "$DST/$name"
    case "$name" in
      *STATUS*) echo "STATUS $name $(cat "$DST/$name")"; exit 0 ;;
      *) res=$(cd "$SCR" && python merge_dom_details.py "$DST/$name" 2>&1 | tr '\n' ' ')
         echo "MERGED $name :: $res" ;;
    esac
  done
  sleep 10
done
