#!/bin/bash
# Copyright (C) 2024 RTE
# SPDX-License-Identifier: Apache-2.0

function addIndexToArray {
  local -n myarray=$1
  for idx in `seq 1 ${#myarray[@]}`; do
    arrVar+=($idx")")
    arrVar+=("${myarray[$(($idx-1))]}")
  done
}
function editKey {
  key=$1
  extension=$2
  file=$(mktemp)$extension
  rbd image-meta get rbd/system_$guest $key >"$file"
  old_metadata=$(ls -li --full-time "$file")
  "${VISUAL:-"${EDITOR:-vi}"}" "$file"
  new_metadata=$(ls -li --full-time "$file")
  if [ "$new_metadata" = "$old_metadata" ]; then
    echo nothing changed
  else
    rbd image-meta set rbd/system_$guest $key "`cat $file`"
    if (whiptail --title "disable/enable guest" --yesno "Can we disable and enable this guest to take the change into account?" 8 78); then
      vm-mgr disable -n $guest
      vm-mgr enable -n $guest
    fi
  fi
}
function editGuest {
  while [ 1 ]
  do
    arrVar0=()
    arrVar=()
    for i in `python3 /usr/local/bin/get_metadata.py $guest`
    do
      arrVar0+=("$i")
    done
    addIndexToArray arrVar0
    CHOICE=$(
    whiptail --title "edit metadata vm $guest" --cancel-button "back" --menu "select key to edit:" 22 115 14 \
          "${arrVar[@]}" \
          3>&2 2>&1 1>&3
    )
    [[ "$?" = 1 ]] && return 1
    c=`echo $CHOICE | sed "s/)//"`
    c=$((($c-1)*2+1))
    key=${arrVar[$c]}
    if [[ "$key" =~ xml$ ]]; then
      extension=".xml"
    fi
    editKey $key $extension
  done
}

guest=$1
[ -z $guest ] || { editGuest; exit; }

while [ 1 ]
do
  arrVar0=()
  arrVar=()
  for i in `rbd list | grep -E "^system_" | sed s/^system_//`
  do
    arrVar0+=("$i")
  done
  addIndexToArray arrVar0
  CHOICE=$(
  whiptail --title "edit metadata vm" --cancel-button "exit" --menu "select guest to edit:" 22 115 14 \
        "${arrVar[@]}" \
        3>&2 2>&1 1>&3
  )
  [[ "$?" = 1 ]] && break
  c=`echo $CHOICE | sed "s/)//"`
  c=$((($c-1)*2+1))
  guest=${arrVar[$c]}
  editGuest
done


