# Turner C3 Fluorometer Operations Guide

**Category:** procedures
**Tags:** turner, c3, fluorometer, sensor, sampling, payload, g1, sv3, chlorophyll
**Last Updated:** 2024-12-19
**Applies To:** Wave Glider SV3

## Overview

This guide covers operational procedures for the Turner C3 Fluorometer on Wave Glider SV3. The C3 Fluorometer is a chlorophyll fluorescence sensor connected to the science computer/SMC and controlled through the G1_C3 command interface. This document includes power management, sampling parameter configuration, and standard operating procedures for the fluorometer.

---

## Prerequisites

Before operating the Turner C3 Fluorometer, ensure you have:

- [ ] Access to SV3 Commands interface
- [ ] Science computer/G1Integrator is powered on
- [ ] Understanding of desired sampling frequency
- [ ] Knowledge of mission power budget requirements

---

## Command Location

The Turner C3 Fluorometer commands are located in the SV3 Commands interface:

**Path:** `SV3 Commands > Payload > G1_C3`

---

## Procedure: Turn On the C3 Fluorometer

### Prerequisites

**CRITICAL:** The science computer/G1Integrator must be powered on before turning on any science sensors, including the C3 Fluorometer.

### Steps

1. **Navigate to sampling command**
   - Path: `SV3 Commands > Payload > G1_C3 > Start Sampling/Set Parameter`
   - Expected: Parameter input interface displays

2. **Enter sampling parameters**
   - Action: Fill in all required parameter fields:
     - **UsePump (true/false):** `true`
     - **Flush:** `100`
     - **Average period/Block:** `60`
     - **Offtime:** `10640`
   - **Important:** You must fill in all parameters before pressing the start sampling/set parameter button. Without valid parameters, the command will not execute

3. **Execute sampling command**
   - Action: Press the "Start Sampling/Set Parameter" button
   - Expected: C3 Fluorometer begins sampling according to configured parameters

4. **Verify sampling status**
   - Action: Monitor initial sampling cycle
   - Expected: Fluorometer samples for 1 minute, then enters sleep period

---

## Procedure: Turn Off the C3 Fluorometer

### Steps

1. **Navigate to stop command**
   - Path: `SV3 Commands > Payload > G1_C3 > Stop`
   - Expected: Stop command interface displays

2. **Execute stop command**
   - Action: Press the Stop button
   - Expected: C3 Fluorometer stops sampling and powers down

3. **Verify shutdown**
   - Action: Confirm sampling has ceased
   - Expected: No active sampling activity

---

## Sampling Parameter Configuration

### Standard Configuration

The standard C3 Fluorometer configuration uses the following parameters:

| Parameter | Value | Description |
|-----------|-------|-------------|
| UsePump (true/false) | true | Enables pump for sample flushing |
| Flush | 100 | Flush time in seconds before sampling |
| Average period/Block | 60 | Number of samples per block (60 samples) |
| Offtime | 10640 | Sleep time in seconds between sampling blocks |

### Sampling Behavior

With the standard configuration, the C3 Fluorometer operates on a 3-hour cycle:

- **Sampling Duration:** 1 minute (60 samples at 1 Hz)
- **Flush Time:** 100 seconds before each sampling block
- **Sleep Duration:** 2 hours 59 minutes (10640 seconds)
- **Total Cycle Time:** 3 hours

**Summary:** The fluorometer samples for 1 minute with a 100-second flush every 3 hours.

### Parameter Details

#### UsePump (true/false)

Controls whether the pump is used for sample flushing.

- **true:** Pump is active, provides better sample flushing
- **false:** Pump is disabled (not typically used)

#### Flush

Time in seconds the sensor flushes before beginning a sampling block. This ensures the sensor chamber is cleared of old water and filled with fresh sample water.

- **Standard Value:** 100 seconds

#### Average period/Block

The number of individual samples collected during each sampling block.

- **Standard Value:** 60 samples
- **Sampling Rate:** 1 Hz (1 sample per second)
- **Block Duration:** 60 seconds (1 minute)

#### Offtime

The sleep period in seconds between sampling blocks. During this time, the sensor is inactive to conserve power.

- **Standard Value:** 10640 seconds (2 hours 59 minutes)
- **Calculation:** 3 hours = 10800 seconds, minus 60 seconds sampling = 10740 seconds, minus 100 seconds flush = 10640 seconds

---

## Quick Reference

| Task | Command Path | Required Parameters |
|------|--------------|---------------------|
| Turn On | `SV3 Commands > Payload > G1_C3 > Start Sampling/Set Parameter` | UsePump: true, Flush: 100, Average period/Block: 60, Offtime: 10640 |
| Turn Off | `SV3 Commands > Payload > G1_C3 > Stop` | None |

---

## Sampling Cycle Timeline

| Phase | Duration | Description |
|-------|----------|-------------|
| Flush | 100 seconds | Sensor flushes chamber with fresh water |
| Sampling | 60 seconds | Collects 60 samples at 1 Hz |
| Sleep | 10640 seconds | Sensor inactive to conserve power |
| **Total Cycle** | **10800 seconds (3 hours)** | Complete cycle repeats |

---

## Troubleshooting This Procedure

| Problem During Procedure | Solution |
|--------------------------|----------|
| Command does not execute | Ensure all parameter fields are filled with valid values before pressing button |
| Sensor does not start sampling | Verify science computer/G1Integrator is powered on first |
| Sampling parameters not accepted | Confirm all four parameters (UsePump, Flush, Average period/Block, Offtime) are entered |
| Sensor samples continuously without sleep | Check that Offtime parameter is set correctly (should be 10640 for 3-hour cycle) |
| Pump not operating | Verify UsePump parameter is set to `true` |

---

## Important Notes

- **Power Sequence:** Always power on the science computer/G1Integrator before powering on the C3 Fluorometer or any other science sensors
- **Parameter Requirements:** All commands that require parameters must have all parameter fields filled before the command button is pressed
- **Sampling Cycle:** The standard configuration samples for 1 minute every 3 hours, which balances data collection with power conservation
- **Flush Time:** The 100-second flush ensures accurate readings by clearing old water from the sensor chamber
- **Command Path:** All C3 Fluorometer commands are located under `SV3 Commands > Payload > G1_C3`

---

## Related Resources

- [Sensor specifications and calibration procedures]
- [Power management and budgeting guidelines]
- [Science computer/G1Integrator operations]
- [Chlorophyll fluorescence data interpretation]

