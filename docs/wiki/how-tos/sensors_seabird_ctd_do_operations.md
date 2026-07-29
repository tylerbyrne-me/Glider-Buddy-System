# Seabird CTD+DO Sensor Operations Guide

**Category:** procedures
**Tags:** seabird, ctd, dissolved-oxygen, sensor, sampling, payload, g1, sv3
**Last Updated:** 2024-12-19
**Applies To:** Wave Glider SV3

## Overview

This guide covers operational procedures for the Seabird CTD+DO (Conductivity, Temperature, Depth + Dissolved Oxygen) sensor on Wave Glider SV3. The CTD+DO sensor is connected to the science computer/SMC (Science Mission Computer) and controlled through the SBGPCTD (SeaBird Glider Payload CTD) command interface. This document includes power management, sampling parameter configuration, status checking, and standard operating procedures.

---

## Prerequisites

Before operating the Seabird CTD+DO sensor, ensure you have:

- [ ] Access to SV3 Commands interface
- [ ] Science computer/G1Integrator is powered on
- [ ] Knowledge of current mission power budget requirements
- [ ] Understanding of desired sampling frequency

---

## Command Location

The Seabird CTD+DO sensor commands are located in the SV3 Commands interface:

**Path:** `SV3 Commands > Payload > G1_SBGPCTD`

**SBGPCTD** stands for SeaBird Glider Payload CTD.

---

## Procedure: Power On the CTD+DO Sensor

### Prerequisites

**CRITICAL:** The science computer/G1Integrator must be powered on before turning on any science sensors, including the CTD+DO.

### Steps

1. **Navigate to power command**
   - Path: `SV3 Commands > Payload > G1_SBGPCTD > Power`
   - Expected: Power command interface displays

2. **Enter power parameter**
   - Action: Fill in the parameter field with `"true"` (include quotes)
   - **Important:** You must fill in the parameter before pressing the power button. Without a valid parameter, the command will not execute

3. **Execute power command**
   - Action: Press the power button
   - Expected: CTD+DO sensor powers on

4. **Verify power status**
   - Action: Check status using procedure below
   - Expected: Status shows CTD is on

---

## Procedure: Configure Sampling Parameters

### Overview

The CTD+DO sensor requires specific sampling parameters to be set before it begins collecting data. Parameters control sampling frequency, block size, flush time, and off time between sampling cycles.

### Standard Sampling Configurations

#### Hourly Sampling (Typical Configuration)

For sampling every 60 minutes (10 samples per hour):

| Parameter | Value | Description |
|-----------|-------|-------------|
| Period (sec) | 10 | Time between individual samples |
| Block size | 10 | Number of samples per block |
| Flush time (sec) | 100 | Time to flush sensor before sampling |
| Off time (sec) | 3400 | Time between sampling blocks |

#### 15-Minute Sampling (High Frequency)

For sampling every 15 minutes:

| Parameter | Value | Description |
|-----------|-------|-------------|
| Period (sec) | 10 | Time between individual samples |
| Block size | 10 | Number of samples per block |
| Flush time (sec) | 100 | Time to flush sensor before sampling |
| Off time (sec) | 700 | Time between sampling blocks |

**Note:** Sampling frequency may vary based on mission requirements and power budget constraints. Always confirm current parameters with a senior pilot before configuring.

### Steps

1. **Navigate to sampling command**
   - Path: `SV3 Commands > Payload > G1_SBGPCTD > Start Sampling/Set Parameter`
   - Expected: Parameter input interface displays

2. **Enter sampling parameters**
   - Action: Fill in all required parameter fields:
     - Period (sec): [value based on desired frequency]
     - Block size: [typically 10]
     - Flush time (sec): [typically 100]
     - Off time: [value based on desired frequency]
   - **Important:** You must fill in all parameters before pressing the start sampling/set parameter button. Without valid parameters, the command will not execute

3. **Execute sampling command**
   - Action: Press the "Start Sampling/Set Parameter" button
   - Expected: CTD+DO sensor begins sampling according to configured parameters

4. **Verify sampling status**
   - Action: Check status using procedure below
   - Expected: Status confirms sampling is active

---

## Procedure: Check CTD+DO Status

### Steps

1. **Navigate to status command**
   - Path: `SV3 Commands > Payload > G1_SBGPCTD > Status`
   - Expected: Status command interface displays

2. **Execute status command**
   - Action: Press the Status button
   - Expected: Status output appears in the commands log

3. **Review status output**
   - Location: Commands log
   - Information: Status indicates whether the CTD+DO sensor is powered on or off, and whether sampling is active

---

## Procedure: Power Off the CTD+DO Sensor

### Steps

1. **Stop sampling (if active)**
   - Path: `SV3 Commands > Payload > G1_SBGPCTD > Stop Sampling`
   - Action: Press the Stop Sampling button
   - Expected: Sampling activity ceases

2. **Navigate to power command**
   - Path: `SV3 Commands > Payload > G1_SBGPCTD > Power`
   - Expected: Power command interface displays

3. **Enter power parameter**
   - Action: Fill in the parameter field with `"false"` (include quotes)
   - **Important:** You must fill in the parameter before pressing the power button. Without a valid parameter, the command will not execute

4. **Execute power command**
   - Action: Press the power button
   - Expected: CTD+DO sensor powers off

5. **Verify power status**
   - Action: Check status using procedure above
   - Expected: Status shows CTD is off

---

## Quick Reference

| Task | Command Path | Required Parameter |
|------|--------------|-------------------|
| Power On | `SV3 Commands > Payload > G1_SBGPCTD > Power` | `"true"` |
| Power Off | `SV3 Commands > Payload > G1_SBGPCTD > Power` | `"false"` |
| Start Sampling | `SV3 Commands > Payload > G1_SBGPCTD > Start Sampling/Set Parameter` | Period, Block size, Flush time, Off time |
| Stop Sampling | `SV3 Commands > Payload > G1_SBGPCTD > Stop Sampling` | None |
| Check Status | `SV3 Commands > Payload > G1_SBGPCTD > Status` | None |

---

## Common Parameter Configurations

| Sampling Frequency | Period (sec) | Block Size | Flush Time (sec) | Off Time (sec) |
|-------------------|-------------|------------|------------------|----------------|
| Every 15 minutes | 10 | 10 | 100 | 700 |
| Every 60 minutes (hourly) | 10 | 10 | 100 | 3400 |

---

## Troubleshooting This Procedure

| Problem During Procedure | Solution |
|--------------------------|----------|
| Command does not execute | Ensure parameter field is filled with valid value (including quotes for power commands) |
| Sensor does not power on | Verify science computer/G1Integrator is powered on first |
| Sampling parameters not accepted | Confirm all four parameters (Period, Block size, Flush time, Off time) are entered before pressing button |
| Status shows sensor off when expected on | Re-check power command was executed with `"true"` parameter |

---

## Important Notes

- **Power Sequence:** Always power on the science computer/G1Integrator before powering on the CTD+DO sensor or any other science sensors
- **Parameter Requirements:** All commands that require parameters must have the parameter field filled before the command button is pressed
- **Sampling Frequency:** Standard configurations are provided, but actual parameters may vary based on mission requirements and power budget. Always confirm with senior pilot before configuring
- **Command Path:** All CTD+DO commands are located under `SV3 Commands > Payload > G1_SBGPCTD`

---

## Related Resources

- [Sensor specifications and calibration procedures]
- [Power management and budgeting guidelines]
- [Science computer/G1Integrator operations]

