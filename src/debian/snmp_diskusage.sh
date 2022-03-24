#!/bin/bash

FILE=/tmp/guest_diskusage.txt

function create_or_rewrite {
  /usr/local/bin/virt-df.sh > $FILE
}

if [ -f $FILE ]
then
  OLDTIME=3600
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
