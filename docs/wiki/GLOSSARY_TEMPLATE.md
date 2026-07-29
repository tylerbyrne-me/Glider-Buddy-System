# Wave Glider Glossary Template

This document provides a template for creating glossary entries that work well with the RAG chatbot system.

---

## Glossary Entry Format

Each glossary entry should include:

```
**Term:** [Primary Term Name]
**Synonyms:** [Alternative names, abbreviations]
**Category:** [System area: navigation, power, sensors, comms, data, etc.]
**Definition:** [Clear, concise definition]
**Context:** [When/where this term is used]
**Related Terms:** [Links to other glossary entries]
**Example:** [Optional: Real-world usage example]
```

---

## Example Glossary Entries

### Navigation & Waypoints

---

**Term:** Arrival Distance
**Synonyms:** Arrival Radius, Waypoint Proximity Threshold
**Category:** Navigation
**Definition:** The distance from a waypoint at which the Command & Control (C&C) computer determines that the vehicle has "arrived" at that waypoint. Once the vehicle is within this distance, it will proceed to the next waypoint or execute the programmed arrival behavior.
**Context:** Configured in WGMS mission planning. Typical values range from 50-500 meters depending on mission requirements and sea conditions.
**Related Terms:** Waypoint, Mission Plan, Loiter Point
**Example:** If Arrival Distance is set to 100m and the glider is 95m from the waypoint, the C&C will consider the waypoint reached and move to the next task.

---

**Term:** Waypoint
**Synonyms:** WP, Nav Point
**Category:** Navigation
**Definition:** A geographic coordinate (latitude/longitude) that defines a target location for the Wave Glider to navigate toward. Waypoints are connected to form a mission track.
**Context:** Created in WGMS Mission Planner or via direct commands.
**Related Terms:** Arrival Distance, Mission Plan, Track Line

---

**Term:** Loiter
**Synonyms:** Station Keep, Hold Position
**Category:** Navigation
**Definition:** A navigation mode where the Wave Glider maintains position within a specified area around a waypoint rather than proceeding to the next waypoint. The vehicle will circle or oscillate to stay within the loiter radius.
**Context:** Used when the glider needs to remain in one location for data collection or to wait for conditions/commands.
**Related Terms:** Arrival Distance, Waypoint, Loiter Radius

---

### Power Systems

---

**Term:** CCU
**Synonyms:** Central Control Unit, Main Battery
**Category:** Power
**Definition:** The Central Control Unit is the primary battery and control system housed in the float. It contains the main power storage (900 Wh base capacity), communications hardware, and core navigation systems.
**Context:** Battery status is monitored via WGMS telemetry. The CCU powers all float systems and can supply power to connected APUs and science payloads.
**Related Terms:** APU, G Port, Battery Capacity

---

**Term:** APU
**Synonyms:** Auxiliary Power Unit, External Battery
**Category:** Power
**Definition:** An Auxiliary Power Unit provides additional battery capacity beyond the CCU. Each APU adds approximately 900 Wh of storage. APUs connect to G ports and provide power only (no communication).
**Context:** Used for extended missions or high-power science payloads. Standard configurations: CCU only (900 Wh), CCU + 1 APU (1800 Wh), CCU + 2 APUs (2700 Wh).
**Related Terms:** CCU, G Port, Power Budget

---

**Term:** G Port
**Synonyms:** General Expansion Port, Gx Port
**Category:** Power
**Definition:** General Expansion Ports on the CCU that provide power and/or communication connections. G1, G2, G3 are typical port designations. Used to connect APUs (power only) or Integrator Payloads/SMCs (power + ethernet).
**Context:** Commands in WGMS: SV3 Commands > Devices > G1/G2/G3. Use Gx for APUs, GxIntegrator for science computers.
**Related Terms:** APU, SMC, Integrator Payload

---

### Sensors & Payloads

---

**Term:** SMC
**Synonyms:** Science Management Computer, Integrator Payload, Science Computer
**Category:** Sensors
**Definition:** The Science Management Computer is the onboard computer that manages science sensor payloads. It communicates with sensors (CTD, fluorometer, etc.) and relays data through the CCU.
**Context:** Must be powered on before any science sensors. Commands via GxIntegrator ports.
**Related Terms:** G Port, CTD, Payload

---

**Term:** CTD
**Synonyms:** Conductivity-Temperature-Depth, Seabird GPCTD, SBGPCTD
**Category:** Sensors
**Definition:** A sensor package that measures water Conductivity, Temperature, and Depth (pressure). The Seabird GPCTD model also includes Dissolved Oxygen capability. Primary instrument for oceanographic measurements.
**Context:** Data appears in WGMS under "Seabird CTD Records with D.O." or "Seabird CTD Records".
**Related Terms:** SMC, Dissolved Oxygen, Salinity

---

**Term:** Sampling Rate
**Synonyms:** Sample Interval, Collection Frequency
**Category:** Sensors
**Definition:** The frequency at which a sensor collects and reports data. Configured via period, block size, and off-time parameters. Higher sampling rates provide more data but consume more power.
**Context:** Balance between data resolution and power budget. Common configurations: hourly (off-time: 3400s), 15-minute (off-time: 700s).
**Related Terms:** Power Budget, Off-time, Block Size

---

### Communications

---

**Term:** Iridium
**Synonyms:** Satellite Comms, SBD
**Category:** Communications
**Definition:** The satellite communication system used for two-way data transfer between the Wave Glider and shore. Uses Short Burst Data (SBD) for telemetry and commands.
**Context:** Primary communication method when out of range of cellular or WiFi. Bandwidth limited; large data transfers may be queued or compressed.
**Related Terms:** Telemetry, WGMS, Command Queue

---

**Term:** Telemetry
**Synonyms:** Telem, Vehicle Status
**Category:** Communications
**Definition:** Data transmitted from the Wave Glider to shore systems showing vehicle status, position, sensor readings, and system health. Updated periodically based on communication schedule.
**Context:** Viewed in WGMS dashboards. Includes position, battery, speed, heading, and sensor summaries.
**Related Terms:** Iridium, WGMS, Status Report

---

### Data & Operations

---

**Term:** WGMS
**Synonyms:** Wave Glider Management System
**Category:** Operations
**Definition:** The web-based software platform for monitoring and controlling Wave Glider missions. Provides dashboards, data visualization, command interfaces, and mission planning tools.
**Context:** Primary interface for pilots to monitor vehicle status and send commands.
**Related Terms:** Telemetry, Mission Plan, Commands

---

**Term:** PIC
**Synonyms:** Pilot in Command, Primary Pilot
**Category:** Operations
**Definition:** The Pilot in Command is the person currently responsible for monitoring and operating a Wave Glider mission. PIC status is tracked for accountability and shift handoffs.
**Context:** PIC handoffs should include mission status, known issues, and pending actions.
**Related Terms:** Handoff, Mission Status, Watch Schedule

---

## Adding New Glossary Entries

When adding new terms:

1. **Check for duplicates** - Search existing glossary first
2. **Include synonyms** - List all variations users might search for
3. **Be specific** - Use your system's exact meaning, not generic definitions
4. **Add context** - Where/when is this term encountered?
5. **Link related terms** - Help users discover connected concepts

## Importing to the Chatbot

Glossary entries can be imported as FAQs using:

```python
# Example: Convert glossary entry to FAQ
faq = {
    "question": "What is Arrival Distance?",
    "answer": "Arrival Distance is the distance from a waypoint at which the C&C computer determines that the vehicle has 'arrived' at that waypoint. Once within this distance (typically 50-500 meters), the vehicle proceeds to the next waypoint. Configure in WGMS mission planning.",
    "category": "glossary",
    "keywords": "arrival distance, arrival radius, waypoint proximity, navigation",
    "tags": "navigation, waypoints, C&C"
}
```

Or use the FAQ Management UI to add entries manually.
