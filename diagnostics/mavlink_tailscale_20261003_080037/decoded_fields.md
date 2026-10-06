# MAVLink UDP 14550 capture

Finished: 2026-10-03T08:00:37.979687+08:00
Duration: 60.01014207800017 s
UDP packets: 6464
Sources: {"('100.100.219.4', 14550)": 6464}

| Message | Count | Approx Hz |
|---|---:|---:|
| GLOBAL_POSITION_INT | 181 | 3.02 |
| SYSTEM_TIME | 181 | 3.02 |
| AHRS | 181 | 3.02 |
| RANGEFINDER | 181 | 3.02 |
| DISTANCE_SENSOR | 362 | 6.03 |
| TERRAIN_REPORT | 181 | 3.02 |
| GIMBAL_DEVICE_ATTITUDE_STATUS | 181 | 3.02 |
| EKF_STATUS_REPORT | 181 | 3.02 |
| VIBRATION | 181 | 3.02 |
| BATTERY_STATUS | 181 | 3.02 |
| ESC_TELEMETRY_1_TO_4 | 181 | 3.02 |
| ESC_TELEMETRY_5_TO_8 | 181 | 3.02 |
| ATTITUDE | 601 | 10.01 |
| VFR_HUD | 600 | 10.00 |
| SCALED_IMU | 600 | 10.00 |
| AHRS2 | 600 | 10.00 |
| COMMAND_ACK | 6 | 0.10 |
| SYS_STATUS | 120 | 2.00 |
| POWER_STATUS | 120 | 2.00 |
| MEMINFO | 120 | 2.00 |
| NAV_CONTROLLER_OUTPUT | 120 | 2.00 |
| MISSION_CURRENT | 120 | 2.00 |
| SERVO_OUTPUT_RAW | 120 | 2.00 |
| RC_CHANNELS | 120 | 2.00 |
| RAW_IMU | 120 | 2.00 |
| SCALED_IMU2 | 120 | 2.00 |
| SCALED_PRESSURE | 120 | 2.00 |
| GPS_RAW_INT | 120 | 2.00 |
| FENCE_STATUS | 120 | 2.00 |
| MCU_STATUS | 120 | 2.00 |
| EXTENDED_SYS_STATE | 60 | 1.00 |
| HEARTBEAT | 60 | 1.00 |
| GIMBAL_MANAGER_STATUS | 12 | 0.20 |
| PARAM_VALUE | 2 | 0.03 |
| STATUSTEXT | 4 | 0.07 |
| TIMESYNC | 6 | 0.10 |

## Latest decoded fields (raw MAVLink units)

### 1:1:GLOBAL_POSITION_INT

```json
{
  "mavpackettype": "GLOBAL_POSITION_INT",
  "time_boot_ms": 1947203,
  "lat": 0,
  "lon": 0,
  "alt": 30,
  "relative_alt": -3557,
  "vx": 0,
  "vy": 0,
  "vz": 0,
  "hdg": 22840
}
```

### 1:1:SYSTEM_TIME

```json
{
  "mavpackettype": "SYSTEM_TIME",
  "time_unix_usec": 0,
  "time_boot_ms": 1947203
}
```

### 1:1:AHRS

```json
{
  "mavpackettype": "AHRS",
  "omegaIx": 0.006461156997829676,
  "omegaIy": -0.002675902098417282,
  "omegaIz": 0.00017158669652417302,
  "accel_weight": 0.0,
  "renorm_val": 0.0,
  "error_rp": 0.0003102092305198312,
  "error_yaw": 0.0013338153949007392
}
```

### 1:1:RANGEFINDER

```json
{
  "mavpackettype": "RANGEFINDER",
  "distance": 0.19380000233650208,
  "voltage": 0.0
}
```

### 1:1:DISTANCE_SENSOR

```json
{
  "mavpackettype": "DISTANCE_SENSOR",
  "time_boot_ms": 1947203,
  "min_distance": 29,
  "max_distance": 2500,
  "current_distance": 37,
  "type": 0,
  "id": 10,
  "orientation": 0,
  "covariance": 0,
  "horizontal_fov": 0.0,
  "vertical_fov": 0.0,
  "quaternion": [
    0.0,
    0.0,
    0.0,
    0.0
  ],
  "signal_quality": 0
}
```

### 1:1:TERRAIN_REPORT

```json
{
  "mavpackettype": "TERRAIN_REPORT",
  "lat": 0,
  "lon": 0,
  "spacing": 100,
  "terrain_height": 0.0,
  "current_height": 0.0,
  "pending": 56,
  "loaded": 0
}
```

### 1:1:GIMBAL_DEVICE_ATTITUDE_STATUS

```json
{
  "mavpackettype": "GIMBAL_DEVICE_ATTITUDE_STATUS",
  "target_system": 0,
  "target_component": 0,
  "time_boot_ms": 1947203,
  "flags": 44,
  "q": [
    0.9990487098693848,
    -4.7891309804981574e-05,
    -0.04360875487327576,
    -2.0904690245515667e-06
  ],
  "angular_velocity_x": NaN,
  "angular_velocity_y": NaN,
  "angular_velocity_z": NaN,
  "failure_flags": 0,
  "delta_yaw": NaN,
  "delta_yaw_velocity": NaN,
  "gimbal_device_id": 1
}
```

### 1:1:EKF_STATUS_REPORT

```json
{
  "mavpackettype": "EKF_STATUS_REPORT",
  "flags": 231,
  "velocity_variance": 0.0,
  "pos_horiz_variance": 0.0013234687503427267,
  "pos_vert_variance": 0.003594211768358946,
  "compass_variance": 0.0012547220103442669,
  "terrain_alt_variance": 0.0,
  "airspeed_variance": 0.0
}
```

### 1:1:VIBRATION

```json
{
  "mavpackettype": "VIBRATION",
  "time_usec": 1947203332,
  "vibration_x": 0.009641720913350582,
  "vibration_y": 0.013486912474036217,
  "vibration_z": 0.015633707866072655,
  "clipping_0": 0,
  "clipping_1": 0,
  "clipping_2": 0
}
```

### 1:1:BATTERY_STATUS

```json
{
  "mavpackettype": "BATTERY_STATUS",
  "id": 0,
  "battery_function": 0,
  "type": 0,
  "temperature": 32767,
  "voltages": [
    24740,
    65535,
    65535,
    65535,
    65535,
    65535,
    65535,
    65535,
    65535,
    65535
  ],
  "current_battery": 30,
  "current_consumed": 156,
  "energy_consumed": 140,
  "battery_remaining": 95,
  "time_remaining": 0,
  "charge_state": 1,
  "voltages_ext": [
    0,
    0,
    0,
    0
  ],
  "mode": 0,
  "fault_bitmask": 0
}
```

### 1:1:ESC_TELEMETRY_1_TO_4

```json
{
  "mavpackettype": "ESC_TELEMETRY_1_TO_4",
  "temperature": [
    34,
    35,
    44,
    0
  ],
  "voltage": [
    1602,
    1610,
    1579,
    0
  ],
  "current": [
    7411,
    7457,
    8140,
    0
  ],
  "totalcurrent": [
    40513,
    40786,
    42772,
    0
  ],
  "rpm": [
    0,
    0,
    0,
    0
  ],
  "count": [
    18357,
    18356,
    18357,
    0
  ]
}
```

### 1:1:ESC_TELEMETRY_5_TO_8

```json
{
  "mavpackettype": "ESC_TELEMETRY_5_TO_8",
  "temperature": [
    0,
    0,
    52,
    0
  ],
  "voltage": [
    0,
    0,
    1700,
    0
  ],
  "current": [
    0,
    0,
    8168,
    0
  ],
  "totalcurrent": [
    0,
    0,
    42173,
    0
  ],
  "rpm": [
    0,
    0,
    0,
    0
  ],
  "count": [
    0,
    0,
    18357,
    0
  ]
}
```

### 1:1:ATTITUDE

```json
{
  "mavpackettype": "ATTITUDE",
  "time_boot_ms": 1947268,
  "roll": 0.025848498567938805,
  "pitch": 0.013306032866239548,
  "yaw": -2.2968831062316895,
  "rollspeed": -0.0001874561421573162,
  "pitchspeed": -0.002032594056800008,
  "yawspeed": -0.0008018672233447433
}
```

### 1:1:VFR_HUD

```json
{
  "mavpackettype": "VFR_HUD",
  "airspeed": 0.0,
  "groundspeed": 0.005122918635606766,
  "heading": 228,
  "throttle": 0,
  "alt": 0.029999999329447746,
  "climb": -0.002521063666790724
}
```

### 1:1:SCALED_IMU

```json
{
  "mavpackettype": "SCALED_IMU",
  "time_boot_ms": 1947168,
  "xacc": 2,
  "yacc": -25,
  "zacc": -996,
  "xgyro": -7,
  "ygyro": 4,
  "zgyro": 0,
  "xmag": -189,
  "ymag": 221,
  "zmag": 302,
  "temperature": 5108
}
```

### 1:1:AHRS2

```json
{
  "mavpackettype": "AHRS2",
  "roll": 0.024325460195541382,
  "pitch": 0.012111403979361057,
  "yaw": -2.2962758541107178,
  "altitude": -3.549999952316284,
  "lat": 0,
  "lng": 0
}
```

### 1:1:COMMAND_ACK

```json
{
  "mavpackettype": "COMMAND_ACK",
  "command": 512,
  "result": 0,
  "progress": 0,
  "result_param2": 0,
  "target_system": 255,
  "target_component": 235
}
```

### 1:1:SYS_STATUS

```json
{
  "mavpackettype": "SYS_STATUS",
  "onboard_control_sensors_present": 1467088175,
  "onboard_control_sensors_enabled": 1449262383,
  "onboard_control_sensors_health": 1198652719,
  "load": 247,
  "voltage_battery": 24740,
  "current_battery": 30,
  "battery_remaining": 95,
  "drop_rate_comm": 0,
  "errors_comm": 0,
  "errors_count1": 0,
  "errors_count2": 0,
  "errors_count3": 0,
  "errors_count4": 0,
  "onboard_control_sensors_present_extended": 0,
  "onboard_control_sensors_enabled_extended": 0,
  "onboard_control_sensors_health_extended": 0
}
```

### 1:1:POWER_STATUS

```json
{
  "mavpackettype": "POWER_STATUS",
  "Vcc": 0,
  "Vservo": 0,
  "flags": 4
}
```

### 1:1:MEMINFO

```json
{
  "mavpackettype": "MEMINFO",
  "brkval": 0,
  "freemem": 65535,
  "freemem32": 498208
}
```

### 1:1:NAV_CONTROLLER_OUTPUT

```json
{
  "mavpackettype": "NAV_CONTROLLER_OUTPUT",
  "nav_roll": 0.005204256623983383,
  "nav_pitch": -0.00485535804182291,
  "nav_bearing": -131,
  "target_bearing": 0,
  "wp_dist": 0,
  "alt_error": 0.0,
  "aspd_error": 0.0,
  "xtrack_error": 0.0
}
```

### 1:1:MISSION_CURRENT

```json
{
  "mavpackettype": "MISSION_CURRENT",
  "seq": 0,
  "total": 3,
  "mission_state": 2,
  "mission_mode": 0
}
```

### 1:1:SERVO_OUTPUT_RAW

```json
{
  "mavpackettype": "SERVO_OUTPUT_RAW",
  "time_usec": 1946970625,
  "port": 0,
  "servo1_raw": 1000,
  "servo2_raw": 1000,
  "servo3_raw": 1000,
  "servo4_raw": 0,
  "servo5_raw": 0,
  "servo6_raw": 1500,
  "servo7_raw": 1000,
  "servo8_raw": 0,
  "servo9_raw": 0,
  "servo10_raw": 0,
  "servo11_raw": 0,
  "servo12_raw": 0,
  "servo13_raw": 0,
  "servo14_raw": 0,
  "servo15_raw": 0,
  "servo16_raw": 0
}
```

### 1:1:RC_CHANNELS

```json
{
  "mavpackettype": "RC_CHANNELS",
  "time_boot_ms": 1946970,
  "chancount": 16,
  "chan1_raw": 1501,
  "chan2_raw": 1501,
  "chan3_raw": 1501,
  "chan4_raw": 1501,
  "chan5_raw": 1051,
  "chan6_raw": 2051,
  "chan7_raw": 1051,
  "chan8_raw": 1951,
  "chan9_raw": 1051,
  "chan10_raw": 1951,
  "chan11_raw": 1501,
  "chan12_raw": 1051,
  "chan13_raw": 1501,
  "chan14_raw": 1051,
  "chan15_raw": 1051,
  "chan16_raw": 1051,
  "chan17_raw": 0,
  "chan18_raw": 0,
  "rssi": 255
}
```

### 1:1:RAW_IMU

```json
{
  "mavpackettype": "RAW_IMU",
  "time_usec": 1946970683,
  "xacc": 2,
  "yacc": -25,
  "zacc": -995,
  "xgyro": -6,
  "ygyro": 4,
  "zgyro": 0,
  "xmag": -189,
  "ymag": 220,
  "zmag": 304,
  "id": 0,
  "temperature": 5108
}
```

### 1:1:SCALED_IMU2

```json
{
  "mavpackettype": "SCALED_IMU2",
  "time_boot_ms": 1946970,
  "xacc": 0,
  "yacc": -24,
  "zacc": -1004,
  "xgyro": -1,
  "ygyro": -1,
  "zgyro": 0,
  "xmag": 0,
  "ymag": 0,
  "zmag": 0,
  "temperature": 4770
}
```

### 1:1:SCALED_PRESSURE

```json
{
  "mavpackettype": "SCALED_PRESSURE",
  "time_boot_ms": 1946970,
  "press_abs": 1002.225830078125,
  "press_diff": 0.0,
  "temperature": 4982,
  "temperature_press_diff": 0
}
```

### 1:1:GPS_RAW_INT

```json
{
  "mavpackettype": "GPS_RAW_INT",
  "time_usec": 0,
  "fix_type": 1,
  "lat": 0,
  "lon": 0,
  "alt": -17000,
  "eph": 9999,
  "epv": 9999,
  "vel": 0,
  "cog": 0,
  "satellites_visible": 0,
  "alt_ellipsoid": 0,
  "h_acc": 4294967295,
  "v_acc": 4251218944,
  "vel_acc": 999000,
  "hdg_acc": 0,
  "yaw": 0
}
```

### 1:1:FENCE_STATUS

```json
{
  "mavpackettype": "FENCE_STATUS",
  "breach_status": 0,
  "breach_count": 0,
  "breach_type": 0,
  "breach_time": 0,
  "breach_mitigation": 1
}
```

### 1:1:MCU_STATUS

```json
{
  "mavpackettype": "MCU_STATUS",
  "id": 0,
  "MCU_temperature": 5349,
  "MCU_voltage": 3290,
  "MCU_voltage_min": 3261,
  "MCU_voltage_max": 3329
}
```

### 1:1:EXTENDED_SYS_STATE

```json
{
  "mavpackettype": "EXTENDED_SYS_STATE",
  "vtol_state": 3,
  "landed_state": 1
}
```

### 1:1:HEARTBEAT

```json
{
  "mavpackettype": "HEARTBEAT",
  "type": 2,
  "autopilot": 3,
  "base_mode": 89,
  "custom_mode": 5,
  "system_status": 3,
  "mavlink_version": 3
}
```

### 1:1:GIMBAL_MANAGER_STATUS

```json
{
  "mavpackettype": "GIMBAL_MANAGER_STATUS",
  "time_boot_ms": 1944828,
  "flags": 12,
  "gimbal_device_id": 1,
  "primary_control_sysid": 0,
  "primary_control_compid": 0,
  "secondary_control_sysid": 0,
  "secondary_control_compid": 0
}
```

### 1:1:PARAM_VALUE

```json
{
  "mavpackettype": "PARAM_VALUE",
  "param_id": "STAT_RUNTIME",
  "param_value": 172967.0,
  "param_type": 6,
  "param_count": 1141,
  "param_index": 65535
}
```

### 1:1:STATUSTEXT

```json
{
  "mavpackettype": "STATUSTEXT",
  "severity": 2,
  "text": "PreArm: Motors Emergency Stopped",
  "id": 0,
  "chunk_seq": 0
}
```

### 1:1:TIMESYNC

```json
{
  "mavpackettype": "TIMESYNC",
  "tc1": 0,
  "ts1": 1940457919001
}
```
