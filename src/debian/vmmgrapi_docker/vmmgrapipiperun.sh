#!/bin/bash

pipe=/run/vmmgr.pipe
uid=33 #UID of the apache user
secret=$(/usr/bin/cat /vmmgrapi.secret)

while true
do
  if [ ! -p ${pipe} ]
  then
    /usr/bin/rm -rf ${pipe}
    /usr/bin/mkfifo ${pipe}
  fi
  uid1="$(/usr/bin/stat -c '%u' "${pipe}")"
  if [ ${uid1} -ne "${uid}" ]
  then
    /usr/bin/chown ${uid} ${pipe}
  fi
  p="$(/usr/bin/cat ${pipe})"
  code=$(/usr/bin/echo ${p} | /usr/bin/cut -c-30)
  cmd=$(/usr/bin/echo ${p} | /usr/bin/cut -c31-)

  if [ "${code}" == "${secret}" ]
  then
    eval "/usr/bin/timeout 10s ${cmd}" >$pipe 2>&1
  else
    echo "dont try to hack me" >$pipe
  fi
done
