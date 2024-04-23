#!/usr/bin/bash

# Read the LinuxPTP status with the pmc tool and derived the 61850 SmpSynch
# status from it.
# Copyright (C) 2024  Grid to Great B.V.
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301,
# USA.
# https://www.gnu.org/licenses/old-licenses/gpl-2.0.en.html

set -e
set -u


##############################################################################
#
# Specifications
#
##############################################################################

# IEEE Std 1588-2008
#  7.6.2.4 clockClass
#   Table 5 — clockClass specifications
#   +------------+-------------------------------------------------------------+
#   | clockClass | Specification                                               |
#   | (decimal)  |                                                             |
#   +------------+-------------------------------------------------------------+
#   | 0          | Reserved to enable compatibility with future versions.      |
#   | 1-5        | Reserved.                                                   |
#   | 6          | Shall designate a clock that is synchronized to a primary   |
#   |            | reference time source. The timescale distributed shall be   |
#   |            | PTP. A clockClass 6 clock shall not be a slave to another   |
#   |            | clock in the domain.                                        |
#   | 7          | Shall designate a clock that has previously been designated |
#   |            | as clockClass 6 but that has lost the ability to            |
#   |            | synchronize to a primary reference time source and is in    |
#   |            | holdover mode and within holdover specifications. The       |
#   |            | timescale distributed shall be PTP. A clockClass 7 clock    |
#   |            | shall not be a slave to another clock in the domain.        |
#   | 8          | Reserved.                                                   |
#   | 9-10       | Reserved to enable compatibility with future versions.      |
#   | 11-12      | Reserved.                                                   |
#   | 13         | Shall designate a clock that is synchronized to an          |
#   |            | application-specific source of time. The timescale          |
#   |            | distributed shall be ARB. A clockClass 13 clock shall not   |
#   |            | be a slave to another clock in the domain.                  |
#   | 14         | Shall designate a clock that has previously been designated |
#   |            | as clockClass 13 but that has lost the ability to           |
#   |            | synchronize to an application-specific source of time and   |
#   |            | is in holdover mode and within holdover specifications. The |
#   |            | timescale distributed shall be ARB. A clockClass 14 clock   |
#   |            | shall not be a slave to another clock in the domain.        |
#   | 15-51      | Reserved.                                                   |
#   | 52         | Degradation alternative A for a clock of clockClass 7 that  |
#   |            | is not within holdover specification. A clock of clockClass |
#   |            | 52 shall not be a slave to another clock in the domain.     |
#   | 53-57      | Reserved.                                                   |
#   | 58         | Degradation alternative A for a clock of clockClass 14 that |
#   |            | is not within holdover specification. A clock of clockClass |
#   |            | 58 shall not be a slave to another clock in the domain.     |
#   | 59-67      | Reserved.                                                   |
#   | 68-122     | For use by alternate PTP profiles.                          |
#   | 123-127    | Reserved.                                                   |
#   | 128-132    | Reserved.                                                   |
#   | 133-170    | For use by alternate PTP profiles.                          |
#   | 171-186    | Reserved.                                                   |
#   | 187        | Degradation alternative B for a clock of clockClass 7 that  |
#   |            | is not within holdover specification. A clock of clockClass |
#   |            | 187 may be a slave to another clock in the domain.          |
#   | 188-192    | Reserved.                                                   |
#   | 193        | Degradation alternative B for a clock of clockClass 14 that |
#   |            | is not within holdover specification. A clock of clockClass |
#   |            | 193 may be a slave to another clock in the domain.          |
#   | 194-215    | Reserved.                                                   |
#   | 216-232    | For use by alternate PTP profiles.                          |
#   | 233-247    | Reserved.                                                   |
#   | 248        | Default. This clockClass shall be used if none of the other |
#   |            | clockClass definitions apply.                               |
#   | 249-250    | Reserved.                                                   |
#   | 251        | Reserved for version 1 compatibility; see Clause 18.        |
#   | 252-254    | Reserved.                                                   |
#   | 255        | Shall be the clockClass of a slave-only clock; see 9.2.2.   |
#   +------------+-------------------------------------------------------------+
#
#  7.6.2.5 clockAccuracy
#   Table 6 — clockAccuracy enumeration
#   +-------------+---------------------------------------+
#   | Value (hex) | Specification                         |
#   +-------------+---------------------------------------+
#   | 00-1F       | Reserved                              |
#   | 20          | The time is accurate to within 25 ns  |
#   | 21          | The time is accurate to within 100 ns |
#   | 22          | The time is accurate to within 250 ns |
#   | 23          | The time is accurate to within 1 µs   |
#   | 24          | The time is accurate to within 2.5 µs |
#   | 25          | The time is accurate to within 10 µs  |
#   | 26          | The time is accurate to within 25 µs  |
#   | 27          | The time is accurate to within 100 µs |
#   | 28          | The time is accurate to within 250 µs |
#   | 29          | The time is accurate to within 1 ms   |
#   | 2A          | The time is accurate to within 2.5 ms |
#   | 2B          | The time is accurate to within 10 ms  |
#   | 2C          | The time is accurate to within 25 ms  |
#   | 2D          | The time is accurate to within 100 ms |
#   | 2E          | The time is accurate to within 250 ms |
#   | 2F          | The time is accurate to within 1 s    |
#   | 30          | The time is accurate to within 10 s   |
#   | 31          | The time is accurate to >10 s         |
#   | 32-7F       | Reserved                              |
#   | 80-FD       | For use by alternate PTP profiles     |
#   | FE          | Unknown                               |
#   | FF          | Reserved                              |
#   +-------------+---------------------------------------+
#
#  7.6.2.6 timeSource
#   Table 7 — timeSource enumeration
#   +-------------+---------------------+--------------------------------------+
#   | Value (hex) | timeSource          | Description                          |
#   +-------------+---------------------+--------------------------------------+
#   | 10          | ATOMIC_CLOCK        | Any device, or device directly       |
#   |             |                     | connected to such a device, that is  |
#   |             |                     | based on atomic resonance for        |
#   |             |                     | frequency and that has been          |
#   |             |                     | calibrated against international     |
#   |             |                     | standards for frequency and, if the  |
#   |             |                     | PTP timescale is used, time          |
#   | 20          | GPS                 | Any device synchronized to a         |
#   |             |                     | satellite system that distribute     |
#   |             |                     | time and frequency tied to           |
#   |             |                     | international standards              |
#   | 30          | TERRESTRIAL_RADIO   | Any device synchronized via any of   |
#   |             |                     | the radio distribution systems that  |
#   |             |                     | distribute time and frequency tied   |
#   |             |                     | to international standards           |
#   | 40          | PTP                 | Any device synchronized to a         |
#   |             |                     | PTP-based source of time external to |
#   |             |                     | the domain                           |
#   | 50          | NTP                 | Any device synchronized via NTP or   |
#   |             |                     | Simple Network Time Protocol (SNTP)  |
#   |             |                     | to servers that distribute time and  |
#   |             |                     | frequency tied to international      |
#   |             |                     | standards                            |
#   | 60          | HAND_SET            | Used for any device whose time has   |
#   |             |                     | been set by means of a human         |
#   |             |                     | interface based on observation of an |
#   |             |                     | international standards source of    |
#   |             |                     | time to within the claimed clock     |
#   |             |                     | accuracy                             |
#   | 90          | OTHER               | Other source of time and/or          |
#   |             |                     | frequency not covered by other       |
#   |             |                     | values                               |
#   | A0          | INTERNAL_OSCILLATOR | Any device whose frequency is not    |
#   |             |                     | based on atomic resonance nor        |
#   |             |                     | calibrated against international     |
#   |             |                     | standards for frequency, and whose   |
#   |             |                     | time is based on a free-running      |
#   |             |                     | oscillator with epoch determined in  |
#   |             |                     | an arbitrary or unknown manner       |
#   | F0–FE       | For use by          |                                      |
#   |             | alternate           |                                      |
#   |             | PTP profiles        |                                      |
#   | FF          | Reserved            |                                      |
#   +-------------+---------------------+--------------------------------------+
#   | * All unused values in Table 7 are reserved.                             |
#   +-------------+---------------------+--------------------------------------+
#
#   NOTE 1 - The values for clockClass, clockAccuracy, and timeSource should be
#   consistent. For example, a class 6 atomic clock synchronized directly to the
#   GPS system might claim an accuracy of 25 ns, while the same atomic clock not
#   synchronized to GPS but set via a user interface by a user observing a
#   National Institute of Standards and Technology (NIST) server via the Web
#   might claim to be class 6 but with an accuracy of 10 s.
#
#   NOTE 2 - The range from F0 to FE is reserved for use by alternate PTP
#   profiles. It is expected that this range will be used by PTP profiles
#   defining applications that distribute only frequency to define the nature of
#   sources appropriate for frequency distribution.
#
#   NOTE 3 - These designations may or may not carry over a power-fail restart
#   but in any case should reflect the current status of the node. For example,
#   a simple quartz oscillator at turn on would be INTERNAL_OSCILLATOR. If later
#   the epoch was set by hand, it would be HAND_SET, whereas if it later
#   synchronized to GPS, it would be GPS. If it had a battery-backed up
#   real-time clock, this status could survive a power-fail restart although the
#   clockAccuracy and perhaps clockClass would be degraded.


# IEC 61869-9:2016
#  6.904.2 Precision time protocol synchronization
#   This subclause 6.904.2 applies only to merging units claiming precision time
#   protocol (PTP) synchronization.
#
#   Merging unit ports used for sample value transmission shall be capable of
#   receiving time synchronization messages compliant with IEC/IEEE 61850-9-3.
#
#   A synchronizing signal received with the PTP clockClass 6 or 7 shall be
#   sourced by a global area clock. A synchronizing signal received with any
#   other clockClass shall be sourced by a local area clock.


# IEC 61850-9-2:2011+AMD1:2020 CSV
#  9 Synchronization
#   When several sampled values publishers are used by an application, they all
#   shall be synchronized to a common time reference to have their sampling
#   synchronized. Different methods exist to synchronize IEDs, such as using a
#   1PPS optical signal from a GPS clock, but the recommended one is using the
#   Precision Time Protocol over Ethernet specified in IEC 61588:2009.
#
#   When IEC 61588:2009 synchronization protocol (PTP) is used to synchronize a
#   sampled values publisher, all PTP compatible devices within the system shall
#   comply with IEC/IEEE 61850-9-3.
#
#   A synchronized sampled values publisher shall fill SmpCnt, SmpSynch and
#   optionally fields RefrTm and gmIdentity as specified in Table 14.
#
#   The required synchronization accuracy of SV during normal operation or in
#   case of clock failure or repair, as well as the specific resetting event for
#   SmpCnt, is out of scope for this standard; relevant standards such as
#   IEC 61869-9 for digital instrument transformers apply.
#
#   A sampled values publisher shall fill the SmpSynch field of SV messages as
#   follows:
#                                       +---------------------------------+-----------------------------+
#                                       | Synchronization device (3)      |                             |
#                                       | synchronized to the required    |                             |
#                                       | accuracy (1) to a global time   | Synchronization device (3)  |
#                                       | reference.                      | not synchronized to the     |
#                                       | For instance, a GPS clock       | required accuracy (1) to a  |
#                                       | receiving the GPS signal or     | global time reference. (2)  |
#                                       | not receiving the GPS signal    |                             |
#                                       | but still in holdover mode. (2) |                             |
#   +-----------------------------------+---------------------------------+-----------------------------+
#   | Sampled values publisher          |                                 |                             |
#   | synchronized to the required      |                                 |                             |
#   | accuracy (1) to the               |                                 |                             |
#   | synchronization device.           |           SmpSync = 2           |         SmpSync = 1         |
#   | For instance a sampled values     |                                 |                             |
#   | publisher receiving clock signal  |    (global synchronization)     |   (local synchronization)   |
#   | or not receiving clock signal but |                                 |                             |
#   | still in holdover mode            |                                 |                             |
#   +-----------------------------------+---------------------------------+-----------------------------+
#   | Sampled values publisher not      |                                 |                             |
#   | synchronized to the required      |           SmpSync = 0           |         SmpSync = 0         |
#   | accuracy (1) to the               |                                 |                             |
#   | synchronization device.           |    (internally synchronized)    |  (internally synchronized)  |
#   +-----------------------------------+---------------------------------+-----------------------------+
#
#   NOTE 1 The required accuracy depends on the application and the kind of
#   sampled values transported. The accuracy requirements from the application /
#   product standard should apply.
#
#   NOTE 2 The way the sampled values publisher knows if the synchronizing
#   device is synchronized to the required accuracy to a global time reference
#   is out of scope for this standard. The recommended method is using the
#   IEC/IEEE 61850-9-3 for synchronization and quality information sent by the
#   grandmaster clock. For instance, having time traceable flag set to true and
#   a clockClass of 6 for SmpSync = 2.
#
#   NOTE 3 "Synchronization device" could be any device used to synchronize a
#   sampled values publisher, for instance a PTP grandmaster clock, Caesium
#   clock, GPS clock etc.
#
#   Other values are reserved and shall not be used for SmpSynch.
#
#   When PTP is used to synchronize a sampled values publisher, the use of the
#   optional field gmIdentity is strongly recommended to indicate the identity
#   of the grandmaster clock actually synchronizing the device. The value of
#   gmIdentity shall be the network order of the bytes representing
#   grandmasterIdentity according to 13.5 of IEC 61588:2009.
#
#   If SmpSynch = 0 or when PTP is not used to synchronize a sampled values
#   publisher, the information in the gmIdentity field is irrelevant and not
#   defined.
#
#   NOTE Any means to identify a local area clock other than PTP has been
#   deprecated, refer to C.3.4 for compatibility issues.


# IEC/IEEE 61850-9-3:2016
#  7.4.1 Grandmaster time inaccuracy
#   A grandmaster-capable clock shall have a time inaccuracy measured between
#   its applied time reference signal and the produced synchronization messages
#   that is smaller than 250 ns.
#
#   NOTE This value corresponds to an IEC 61588:2009 ¦ IEEE Std 1588-2008
#   clockAccuracy of 22 hex.
#
#   In case the grandmaster-capable clock has no time reference signal,
#   IEC 61588:2009 ¦ IEEE Std 1588-2008, J.4.4.1 shall apply.
#
#  7.4.3 Grandmaster clockQuality in start-up, holdover and recovery
#   A grandmaster clock shall adjust its clockClass according to
#   IEC 61588:2009 ¦ IEEE Std
#   1588-2008, Table 5 with the values:
#     6   while synchronized to its time reference signal and in steady state;
#     7   after loss of its time reference signal, while in holdover;
#     52  after loss of its time reference signal, when its time error exceeds
#         7.4.1;
#     187 after loss of its time reference signal, when its time error exceeds
#         1 µs;
#     6   after recovering the time reference signal and in steady state.
#
#   NOTE 1 This modifies IEC 61588:2009 ¦ IEEE Std 1588-2008, Table 5 with the
#   timing requirements of this profile.
#
#   NOTE 2 The clockClass 6 appears twice in this list, once before loss of time
#   reference signal, and once after recovery thereof.
#
#   NOTE 3 A grandmaster clock adjusts its clockAccuracy and
#   offsetScaledLogVariance according to IEC 61588:2009 ¦ IEEE Std 1588-2008,
#   7.6.2.5 and 7.6.3.


# IEC TR 61850-90-4:2020
#  14.4.5.10 The IEC/IEEE 61850-9-3 Power utility profile (PUP)
#   14.4.5.10.1 PUP profile parameters
#     * IEC 61588 settings:
#       - ...
#       - The grandmaster clockClass is 6 (degraded to 7, 52 and 187 after loss of reference),
#       - ...


##############################################################################
#
# Detailing
#
##############################################################################

# Input requirements:
# - IEC 61869-9:2016 chapter 6.904.2
# - IEC 61850-9-2:2011+AMD1:2020 CSV, chapter 9
# - The local device is a slave-only PTP device
#
# These result in the following detailed requirements:
#
# Requirement 1
# =============
# The presence of a selected grandmaster clock is required for a non-zero
# SmpSync value.
#
#   (TIME_STATUS_NP.gmPresent == true)
#
#
# Requirement 2
# =============
# A clockClass of 6 or 7 is required for a SmpSync of 2.
#
# ((PARENT_DATA_SET.gm.ClockClass == 6) || (PARENT_DATA_SET.gm.ClockClass == 7))
#
#
# Requirement 3
# =============
# A clockAccuracy equal to or better than the specified minimum accuracy is
# required for a SmpSync of 2.
#
# (PARENT_DATA_SET.gm.ClockAccuracy <= STATE_PTP_CLOCK_ACCURACY_MIN)

# Pseudo code:
# if (TIME_STATUS_NP.gmPresent == false)
#   SmpSync = 0
# else if (
#          (PARENT_DATA_SET.gm.ClockClass == 6) ||
#          (PARENT_DATA_SET.gm.ClockClass == 7)
#         ) &&
#         (PARENT_DATA_SET.gm.ClockAccuracy <= STATE_PTP_CLOCK_ACCURACY_MIN)
#   SmpSync = 2
# else
#   SmpSync = 1


##############################################################################
#
# Practical Situations
#
##############################################################################

# The 2 situations below were observed on a slave node that was connected
# to a Cisco IE5000 boundary clock without GPS link, which in turn was
# connected to an ATop transparent clock, which in turn was connect to a
# Meinberg grandmaster clock.
#
# Global Sync (==> grandmaster clock is the Meinberg)
#   PARENT_DATA_SET
#       gm.ClockClass              6
#       gm.ClockAccuracy           0x21
#   TIME_STATUS_NP
#       gmIdentity                 ec4670.fffe.0aadd5
#       gmPresent                  true
#
# Local Sync (==> grandmaster clock is the Cisco)
#   PARENT_DATA_SET
#       gm.ClockClass              248
#       gm.ClockAccuracy           0xfe
#   TIME_STATUS_NP
#       gmIdentity                 3c8b7f.fffe.d63f00
#       gmPresent                  true


##############################################################################
#
# Examples
#
##############################################################################

# Get all available information:
# pmc -u -b 0 \
#   'GET ANNOUNCE_RECEIPT_TIMEOUT' \
#   'GET CLOCK_ACCURACY' \
#   'GET CLOCK_DESCRIPTION' \
#   'GET CURRENT_DATA_SET' \
#   'GET DEFAULT_DATA_SET' \
#   'GET DELAY_MECHANISM' \
#   'GET DOMAIN' \
#   'GET GRANDMASTER_SETTINGS_NP' \
#   'GET LOG_ANNOUNCE_INTERVAL' \
#   'GET LOG_MIN_PDELAY_REQ_INTERVAL' \
#   'GET LOG_SYNC_INTERVAL' \
#   'GET NULL_MANAGEMENT' \
#   'GET PARENT_DATA_SET' \
#   'GET PORT_DATA_SET' \
#   'GET PORT_DATA_SET_NP' \
#   'GET PORT_PROPERTIES_NP' \
#   'GET PORT_STATS_NP' \
#   'GET PRIORITY1' \
#   'GET PRIORITY2' \
#   'GET SLAVE_ONLY' \
#   'GET TIMESCALE_PROPERTIES' \
#   'GET TIME_PROPERTIES_DATA_SET' \
#   'GET TIME_STATUS_NP' \
#   'GET TRACEABILITY_PROPERTIES' \
#   'GET USER_DESCRIPTION' \
#   'GET VERSION_NUMBER'


##############################################################################
#
# Settings
#
##############################################################################

declare -i STATE_PTP_CLOCK_ACCURACY_MIN=0x23 # 1 us


##############################################################################
#
# Constants
#
##############################################################################

declare -i STATUS_CLOCK_SYNC_NONE=0
declare -i STATUS_CLOCK_SYNC_LOCAL=1
declare -i STATUS_CLOCK_SYNC_GLOBAL=2


##############################################################################
#
# State
#
##############################################################################

# Default state
STATE_PTP_GM_PRESENT_DEFAULT="false"
declare -i STATE_PTP_CLOCK_CLASS_DEFAULT=255
declare -i STATE_PTP_CLOCK_ACCURACY_DEFAULT=0xfe

# Live state
STATE_PTP_GM_PRESENT=""
declare -i STATE_PTP_CLOCK_CLASS=0
declare -i STATE_PTP_CLOCK_ACCURACY=0

# Reset state to default
function resetState() {
  STATE_PTP_GM_PRESENT="$STATE_PTP_GM_PRESENT_DEFAULT"
  STATE_PTP_CLOCK_CLASS=$STATE_PTP_CLOCK_CLASS_DEFAULT
  STATE_PTP_CLOCK_ACCURACY=$STATE_PTP_CLOCK_ACCURACY_DEFAULT
}


##############################################################################
#
# Functions
#
##############################################################################

function getPtpStatus() {
  local -n _resultVar="$1"

  # Reset state to default
  resetState

  if [[ ! -d "$PTPDETAILSFILEDIR" ]]; then
    mkdir -p "$PTPDETAILSFILEDIR"
  fi

  if [[ -S /var/run/timemaster/ptp4l.0.socket ]]; then
    PMC_SOCKET_OPTION="-s /var/run/timemaster/ptp4l.0.socket"
  fi

  local _pmcOutput="$( \
    "$PMC_EXE" $PMC_SOCKET_OPTION -u -b 0 \
      'GET TIME_PROPERTIES_DATA_SET' \
      'GET TIME_STATUS_NP' \
      'GET PARENT_DATA_SET' \
      'GET PORT_DATA_SET' \
      2> /dev/null)"
  echo "$_pmcOutput" > "$PTP_DETAILS_FILE"

  # Determine whether a GM clock is present
  STATE_PTP_GM_PRESENT="$( \
    echo "$_pmcOutput" | \
    awk '{ if ((NF == 2) && (tolower($1) == "gmpresent")) print tolower($NF) }' 2> /dev/null \
  )"
  STATE_PTP_GM_PRESENT="${STATE_PTP_GM_PRESENT:-$STATE_PTP_GM_PRESENT_DEFAULT}"

  if [[ "$STATE_PTP_GM_PRESENT" != "true" ]]; then
    # No GM clock is present
    _resultVar=$STATUS_CLOCK_SYNC_NONE
    return
  fi

  # A GM clock is present

  # Determine the GM clock class
  _STATE_PTP_CLOCK_CLASS=$( \
    echo "$_pmcOutput" | \
    awk '{ if ((NF == 2) && (tolower($1) == "gm.clockclass")) print tolower($NF) }' 2> /dev/null \
  )
  STATE_PTP_CLOCK_CLASS=${_STATE_PTP_CLOCK_CLASS:-$STATE_PTP_CLOCK_CLASS_DEFAULT}

  # Determine the GM clock accuracy
  local _STATE_PTP_CLOCK_ACCURACY=$( \
    echo "$_pmcOutput" | \
    awk '{ if ((NF == 2) && (tolower($1) == "gm.clockaccuracy")) print tolower($NF) }' 2> /dev/null \
  )
  STATE_PTP_CLOCK_ACCURACY=${_STATE_PTP_CLOCK_ACCURACY:-$STATE_PTP_CLOCK_ACCURACY_DEFAULT}

  # Determine if the clock class is global
  local -i _clockIsGlobal=0
  if [[ $STATE_PTP_CLOCK_CLASS -eq 6 ]] || \
     [[ $STATE_PTP_CLOCK_CLASS -eq 7 ]]; then
     # The GM clock class is global
    _clockIsGlobal=1
  fi

  # Determine if the GM clock accuracy is within spec
  local -i _clockIsAccurate=0
  if [[ $STATE_PTP_CLOCK_ACCURACY -ge 0x20 ]] || \
     [[ $STATE_PTP_CLOCK_ACCURACY -le $STATE_PTP_CLOCK_ACCURACY_MIN ]]; then
    # The GM clock accuracy is within spec
    _clockIsAccurate=1
  fi

  # Determine SmpSync
  if [[ $_clockIsGlobal -ne 0 ]] && \
     [[ $_clockIsAccurate -ne 0 ]]; then
    _resultVar=$STATUS_CLOCK_SYNC_GLOBAL
  else
    _resultVar=$STATUS_CLOCK_SYNC_LOCAL
  fi
}


# Write the given value into the PTP status file
declare -i STATE_STATUS_CLOCK_SYNC_WRITTEN=-1
function writePtpStatusFile() {
  local -i _ptpStatusNew=$1

  if [[ $STATE_STATUS_CLOCK_SYNC_WRITTEN -ne $_ptpStatusNew ]]; then
    if [[ ! -d "$PTPSTATUSFILEDIR" ]]; then
      mkdir -p "$PTPSTATUSFILEDIR"
    fi

    echo "SmpSync: $STATE_STATUS_CLOCK_SYNC_WRITTEN -> $_ptpStatusNew (gmPresent=$STATE_PTP_GM_PRESENT, gm.ClockClass=$STATE_PTP_CLOCK_CLASS, gm.ClockAccuracy=$STATE_PTP_CLOCK_ACCURACY)"
    echo "$_ptpStatusNew" > "$PTP_STAT_FILE"

    STATE_STATUS_CLOCK_SYNC_WRITTEN=$_ptpStatusNew
  fi
}


##############################################################################
#
# Main
#
##############################################################################

resetState

if [[ "$(whoami 2> /dev/null)" != "root" ]]; then
  echo "ERROR: Program must be run under the root account"
  exit 1
fi

PMC_EXE="$(which pmc 2> /dev/null)"
if [[ -z "$PMC_EXE" ]]; then
  echo "ERROR: Program 'pmc' not found"
  exit 1
fi

if [[ $# -ne 2 ]]; then
  echo "ERROR: Specify the PTP status and details files"
  exit 1
fi

PTP_STAT_FILE="$1"
PTP_DETAILS_FILE="$2"
PTPSTATUSFILEDIR="$(dirname "$PTP_STAT_FILE" 2> /dev/null)"
PTPDETAILSFILEDIR="$(dirname "$PTP_DETAILS_FILE" 2> /dev/null)"

declare -i SMPSYNC=0

while true; do
  getPtpStatus "SMPSYNC"
  writePtpStatusFile $SMPSYNC
  sleep 1
done
