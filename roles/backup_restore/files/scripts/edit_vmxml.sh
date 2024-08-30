#!/bin/bash
# Copyright (C) 2024 RTE
# SPDX-License-Identifier: Apache-2.0

guest=$1
file=$(mktemp)".xml"
rbd image-meta get rbd/system_$guest xml >"$file"
old_metadata=$(ls -li --full-time "$file")
"${VISUAL:-"${EDITOR:-vi}"}" "$file"
new_metadata=$(ls -li --full-time "$file")
if [ "$new_metadata" = "$old_metadata" ]; then
  echo nothing changed
else
  rbd image-meta set rbd/system_$guest xml "`cat $file`"
  if (whiptail --title "disable/enable guest" --yesno "Can we disable and enable this guest to take the change into account?" 8 78); then
    vm-mgr disable -n $guest
    vm-mgr enable -n $guest
  fi
fi
