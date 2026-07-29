# Innovasea VM4 Operations Guide

**Category:** procedures
**Tags:** innovasea, vemco, vm4, receiver, offload, station, vr4, acoustic, telemetry
**Last Updated:** 2024-12-19
**Applies To:** Wave Glider SV3

## Overview

This guide covers operational procedures for the Innovasea VM4 acoustic receiver on Wave Glider SV3. The VM4 is connected to the thrudder port (T1) on the glider but is commanded through the Integrator Payload (Science Mission Computer/SMC). This document includes station visibility configuration, remote offload procedures, health monitoring, station settings updates, and power management.

---

## Prerequisites

Before operating the Innovasea VM4, ensure you have:

- [ ] Access to SV3 Commands interface
- [ ] Access to WGMS (Wave Glider Mission System) map interface
- [ ] Knowledge of target receiver station IDs
- [ ] Understanding of appropriate offload protocols for target stations
- [ ] Station settings parameters (if updating)

---

## Command Location

The Innovasea VM4 commands are located in the SV3 Commands interface:

**Path:** `SV3 Commands > Payload > Gx_VemcoVM4`

**Note:** The VM4 is physically connected to the thrudder port (T1) but all commands are sent through the Integrator Payload interface.

---

## Procedure: Make Stations Visible on WGMS Map

### Overview

Before offloading data from VR4 receiver stations, you must configure the map to display the appropriate receiver lines as waypoints.

### Steps

1. **Access Map Options**
   - Location: WGMS (Wave Glider Mission System) map interface
   - Action: Open Map Options menu

2. **Select Receiver Lines**
   - Action: Select the RVs (Receiver Vessels) for the receiver line you are attempting to offload
   - Available receiver lines:
     - **RV – NCAT VR4 Receivers**
     - **RV – OTN CBS Receiver Line**
     - **RV – OTN HFX VR4 Receiver Line**

3. **Verify Station Display**
   - Expected: Stations appear as white numbered waypoints on the map
   - Action: Click on a waypoint to see the station ID
   - Use: Station IDs are required for remote offload commands

---

## Procedure: Remote Offload from VR4 Station

### Prerequisites

- Station must be visible on WGMS map (see procedure above)
- Wave Glider must be in range of the station according to appropriate protocol
- Station ID must be known (visible by clicking waypoint on map)

### Steps

1. **Verify station visibility**
   - Action: Confirm target station appears as white numbered waypoint on WGMS map
   - Action: Click waypoint to obtain station ID (e.g., "NCAT6-23")

2. **Navigate to remote offload command**
   - Path: `SV3 Commands > Payload > Gx_VemcoVM4 > Remote Offload`
   - Expected: Remote Offload command interface displays with empty field

3. **Enter station ID**
   - Action: Enter the station ID into the empty field next to Remote Offload
   - Format: Station ID as displayed on map (e.g., "NCAT6-23", "HFX002")
   - **Important:** Station ID must match exactly as shown on the map

4. **Execute remote offload command**
   - Action: Click the Remote Offload command button
   - Expected: Offload process begins

5. **Monitor offload progress**
   - Location: Vemco VM4 Information page
   - Expected: Status updates showing offload progress
   - Note: System automatically retrieves two remote health reports:
     - When connecting to a station
     - When completing an offload

---

## Procedure: Get VM4 Health Status

### Get Local Health

Use this command anytime to check the status of the VM4 receiver.

**Purpose:**
- Verify VM4 is still communicating
- Check local receiver status
- Confirm system connectivity

**Steps:**

1. **Navigate to local health command**
   - Path: `SV3 Commands > Payload > Gx_VemcoVM4 > Get Local Health`
   - Expected: Command interface displays

2. **Execute command**
   - Action: Click Get Local Health button
   - Expected: Health status information appears in command log

3. **Review health status**
   - Location: Command log output
   - Information: VM4 communication status and operational state

### Get Remote Health

Use this command to check the health of a remote VR4 station.

**Purpose:**
- Check remote station status
- Verify station connectivity
- Diagnose offload issues

**Prerequisites:**
- Must be actively offloading a station (only works during offload operation)

**Steps:**

1. **Navigate to remote health command**
   - Path: `SV3 Commands > Payload > Gx_VemcoVM4 > Get Remote Health`
   - Expected: Command interface displays

2. **Execute command**
   - Action: Click Get Remote Health button
   - Expected: Remote station health information appears in command log

3. **Review remote health status**
   - Location: Command log output
   - Information: Remote VR4 station operational status

**Note:** The system automatically retrieves two remote health reports:
- When connecting to a station
- When completing an offload

---

## Procedure: Update Station Settings

### Overview

Station settings control transmission rates and power levels for both local (VM4) and remote (VR4) stations. All parameters must be entered in a specific format for the command to execute successfully.

### Allowed Values

#### Transmission Rates (tx_rate)
- **Allowed values:** 300, 600, 800, 1066, 1200 bps
- **Units:** bits per second (bps)

#### Transmission Power Levels (tx_power)
- **Allowed values:** 0, -3, -6, -9, -12, -15, -18, -21 dB
- **Units:** decibels (dB)

### Parameter Format

All parameters must be entered in the following format:

| Parameter | Format Example | Description |
|-----------|----------------|-------------|
| Station name | `"Station name"` | Station identifier in quotes |
| local_tx_rate | `"local_tx_rate=300"` | Local transmission rate with parameter name |
| local_tx_power | `"local_tx_power=-12"` | Local transmission power with parameter name |
| remote_tx_rate | `"remote_tx_rate=300"` | Remote transmission rate with parameter name |
| remote_tx_power | `"remote_tx_power=-12"` | Remote transmission power with parameter name |

### Steps

1. **Navigate to station settings command**
   - Path: `SV3 Commands > Payload > Gx_VemcoVM4 > [Station Settings Command]`
   - Expected: Parameter input interface displays

2. **Enter all required parameters**
   - **CRITICAL:** All empty fields must have valid entries for the command to work
   - Enter parameters in the following order:
     - Station name: `"Station name"` (e.g., `"HFX002"`)
     - local_tx_rate: `"local_tx_rate=300"` (use allowed value: 300, 600, 800, 1066, or 1200)
     - local_tx_power: `"local_tx_power=-12"` (use allowed value: 0, -3, -6, -9, -12, -15, -18, or -21)
     - remote_tx_rate: `"remote_tx_rate=300"` (use allowed value: 300, 600, 800, 1066, or 1200)
     - remote_tx_power: `"remote_tx_power=-12"` (use allowed value: 0, -3, -6, -9, -12, -15, -18, or -21)

3. **Verify parameter format**
   - Ensure all parameters include the parameter name and equals sign
   - Ensure all values are within allowed ranges
   - Ensure station name is in quotes

4. **Execute command**
   - Action: Press the command button
   - Expected: Station settings update confirmation

### Example: Update HFX002 Station

To update station HFX002 to local/remote baud rate 300 bps and local/remote power -12 dB, enter all of the following:

```
HFX002, local_tx_rate=300, local_tx_power=-12, remote_tx_rate=300, remote_tx_power=-12
```

**Important:** If these aren't all entered as shown, the command will not work.

---

## Procedure: Abort Remote Offload

### Steps

1. **Navigate to abort command**
   - Path: `SV3 Commands > Payload > Gx_VemcoVM4 > Abort`
   - Expected: Abort command interface displays

2. **Execute abort command**
   - Action: Click the Abort button
   - Expected: Offload process stops

3. **Verify abort success**
   - Location: Vemco VM4 Information page
   - Expected: Status message displays "remote VR4-###### offload aborted"
   - Action: Confirm abort message appears to verify successful cancellation

---

## Procedure: Power Cycle the VM4

### Overview

The VM4 is connected to the T1 (thrudder port). To cycle power on the VM4, you must use the T1 device power commands. This may be necessary if you need to turn off the science computer, as the VM4 should be powered off first.

### Steps

#### Power Off VM4

1. **Navigate to T1 power command**
   - Path: `SV3 Commands > Devices > T1 > Power Off`
   - Expected: Power command interface displays

2. **Execute power off command**
   - Action: Click Power Off button
   - Expected: VM4 powers down

3. **Verify power off**
   - Action: Check VM4 status or attempt Get Local Health command
   - Expected: No response from VM4

#### Power On VM4

1. **Navigate to T1 power command**
   - Path: `SV3 Commands > Devices > T1 > Power On`
   - Expected: Power command interface displays

2. **Execute power on command**
   - Action: Click Power On button
   - Expected: VM4 powers up

3. **Verify power on**
   - Action: Wait for initialization (typically 30-60 seconds)
   - Action: Use Get Local Health command to confirm communication
   - Expected: VM4 responds with health status

### Important Notes

- **Power Sequence:** If you need to turn off the science computer, turn off the VM4 first using T1 power commands
- **Connection:** The VM4 is physically connected to the T1 port, which is why T1 power commands control it
- **Initialization:** Allow time for VM4 to initialize after power on before attempting commands

---

## Quick Reference

| Task | Command Path | Notes |
|------|--------------|-------|
| Get Local Health | `SV3 Commands > Payload > Gx_VemcoVM4 > Get Local Health` | Use anytime to check VM4 status |
| Get Remote Health | `SV3 Commands > Payload > Gx_VemcoVM4 > Get Remote Health` | Only works during offload |
| Remote Offload | `SV3 Commands > Payload > Gx_VemcoVM4 > Remote Offload` | Enter station ID in field first |
| Abort Offload | `SV3 Commands > Payload > Gx_VemcoVM4 > Abort` | Verify on VM4 Information page |
| Power Off VM4 | `SV3 Commands > Devices > T1 > Power Off` | VM4 connected to T1 port |
| Power On VM4 | `SV3 Commands > Devices > T1 > Power On` | Allow initialization time |

---

## Station Settings Quick Reference

### Allowed Transmission Rates
- 300 bps
- 600 bps
- 800 bps
- 1066 bps
- 1200 bps

### Allowed Transmission Power Levels
- 0 dB
- -3 dB
- -6 dB
- -9 dB
- -12 dB
- -15 dB
- -18 dB
- -21 dB

### Station Settings Format
```
Station name, local_tx_rate=[value], local_tx_power=[value], remote_tx_rate=[value], remote_tx_power=[value]
```

**Example:**
```
HFX002, local_tx_rate=300, local_tx_power=-12, remote_tx_rate=300, remote_tx_power=-12
```

---

## Troubleshooting This Procedure

| Problem During Procedure | Solution |
|--------------------------|----------|
| Stations not visible on map | Select appropriate receiver line (RV) in Map Options |
| Remote offload command doesn't execute | Verify station ID is entered correctly in the field before clicking command |
| Get Remote Health doesn't work | Command only works during active offload operation |
| Station settings update fails | Ensure all five parameters are entered with correct format (parameter name, equals sign, value) |
| Station settings update fails | Verify all values are within allowed ranges (see Allowed Values section) |
| VM4 not responding | Check T1 power status; may need to power cycle |
| Cannot verify abort success | Check Vemco VM4 Information page for "offload aborted" message |

---

## Important Notes

- **Physical Connection:** The VM4 is connected to the T1 (thrudder port) but commanded through the Integrator Payload (SMC) interface
- **Command Path:** All VM4 operational commands are under `SV3 Commands > Payload > Gx_VemcoVM4`
- **Power Commands:** VM4 power is controlled through `SV3 Commands > Devices > T1` (not through Payload commands)
- **Station Settings:** All five parameters must be entered with correct format for settings update to work
- **Automatic Health Reports:** System automatically retrieves remote health reports when connecting to and completing offloads
- **Map Visibility:** Stations must be made visible via Map Options before offload can be initiated

---

## Related Resources

- **Slack Bookmarked Items:**
  - VR4 Station Offloads and Stats
  - VM4 Commands and Protocols
  - Offload training video
- [Science computer/G1Integrator operations]
- [WGMS map interface documentation]
- [Acoustic telemetry protocols]

