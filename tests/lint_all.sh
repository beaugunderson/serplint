#!/bin/bash

for FILE in *.se;
do
  echo "$FILE"
  echo

  ../serplint.py "$FILE"

  echo
done
