#!/usr/bin/python3 -u

# This file is part of the SEAPATH PROJECT (https://github.com/seapath).
# Copyright (c) 2024 RTE RESEAU DE TRANSPORT D'ELECTRICITE
# 
# It imports the snmp_passpersist module (https://github.com/nagius/snmp_passpersist)
# which is at this time licensed under the GNU General Public License
# as published by the Free Software Foundation, version 3, and so
# needs itself to be license under the same GPL v3.
# 
# This program is free software: you can redistribute it and/or modify  
# it under the terms of the GNU General Public License as published by  
# the Free Software Foundation, version 3.
#
# This program is distributed in the hope that it will be useful, but 
# WITHOUT ANY WARRANTY; without even the implied warranty of 
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU 
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License 
# along with this program. If not, see <http://www.gnu.org/licenses/>.

import snmp_passpersist as snmp
import subprocess

def my_setter(oid, type, value):
    try:
        subprocess.run(value.split(" "))
    except:
        pass
    return True

def update():
    pp.add_str('0.0', "seapath")
    file_path = "/tmp/snmpdata.txt"
    with open(file_path, "r") as file:
        for line in file:
            # Split the line at the first ":" character
            parts = line.split(":", 1)

            # Ensure that there is at least one ":" character in the line
            if len(parts) == 2:
                oid = parts[0].strip()
                value = parts[1].strip()
                pp.add_str("0"+oid, value[0:4000])

pp=snmp.PassPersist(".2.25.1936023920.1635018752")
pp.register_setter('.2.25.1936023920.1635018752.0.0', my_setter)
pp.start(update,300)
