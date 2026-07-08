#!/bin/bash
# Copyright (C) 2024 RTE
# SPDX-License-Identifier: Apache-2.0

# Display a whiptail menu over the given items and print the (0-based) index
# of the selected one. Returns 1 if the user chose "back", 2 for "(exit)".
function menuChooseIndex {
  local title=$1 prompt=$2
  shift 2
  local items=("$@")
  local args=() idx choice
  for idx in "${!items[@]}"; do
    args+=("$((idx + 1)))" "${items[$idx]}")
  done
  args+=("(exit)" " ")
  choice=$(whiptail --title "$title" --cancel-button "back" --menu "$prompt" 22 115 14 \
           "${args[@]}" 3>&2 2>&1 1>&3) || return 1
  [[ "$choice" == "(exit)" ]] && return 2
  echo "$((${choice%")"} - 1))"
}

function editKey {
  local key=$1 extension=$2
  local file old_metadata new_metadata
  file=$(mktemp)$extension
  rbd image-meta get "rbd/system_$guest" "$key" >"$file"
  old_metadata=$(ls -li --full-time "$file")
  "${VISUAL:-"${EDITOR:-vi}"}" "$file"
  new_metadata=$(ls -li --full-time "$file")
  if [ "$new_metadata" = "$old_metadata" ]; then
    echo nothing changed
  else
    rbd image-meta set "rbd/system_$guest" "$key" "$(cat "$file")"
    if (whiptail --title "disable/enable guest" --yesno "Can we disable and enable this guest to take the change into account?" 8 78); then
      vm-mgr disable -n "$guest"
      vm-mgr enable -n "$guest"
    fi
  fi
}

function editGuest {
  while true
  do
    local keys=($(python3 /usr/local/bin/get_metadata.py "$guest"))
    local idx key extension
    idx=$(menuChooseIndex "edit metadata vm $guest" "select key to edit:" "${keys[@]}")
    case $? in 1) return ;; 2) exit ;; esac
    key=${keys[$idx]}
    extension=""
    [[ "$key" =~ xml$ ]] && extension=".xml"
    editKey "$key" "$extension"
  done
}

guest=${1:-}
[ -n "$guest" ] && { editGuest; exit; }

while true
do
  guests=($(rbd list | grep -E "^system_" | sed s/^system_//))
  idx=$(menuChooseIndex "edit metadata vm" "select guest to edit:" "${guests[@]}")
  case $? in 1) break ;; 2) exit ;; esac
  guest=${guests[$idx]}
  editGuest
done
