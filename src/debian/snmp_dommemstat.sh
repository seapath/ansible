#!/bin/bash

FILE=/tmp/dommemstat.txt

function create_or_rewrite {
  /usr/bin/virsh --connect qemu:///system list --name | sed -s "/^$/d" | while read i
  do
    echo Domain: \'$i\'
    /usr/bin/virsh --connect qemu:///system dommemstat --domain $i
  done > $FILE
}

if [ -f $FILE ]
then
  OLDTIME=60
  CURTIME=$(date +%s)
  FILETIME=$(stat $FILE -c %Y)
  TIMEDIFF=$(expr $CURTIME - $FILETIME)

  if [ $TIMEDIFF -gt $OLDTIME ]; then
    create_or_rewrite
  fi
else
  create_or_rewrite
fi
cat $FILE
