#!/usr/bin/env bash

METHOD_NAME="mut_756596dc"
FILE_PATH="../workspace/scratch/data/solves/${METHOD_NAME}.csv"

INDEX="$1"

[[ "$INDEX" =~ ^[0-9]+$ ]] || { echo "Usage: $0 <non-negative integer index>"; exit 1; }

LINE_NUM=$((INDEX + 1))

sed -n "${LINE_NUM}p" "$FILE_PATH" \
  | tr ',' '\n' \
  | sed '$d'
