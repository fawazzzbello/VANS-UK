# Directive: Detect Violations

## Goal
Process incoming traffic data and camera feeds to detect driver violations in real time.

## Violation Types

| Code | Type | Detection Method |
|------|------|-----------------|
| SPD | Speeding | Speed camera data vs posted limits |
| RLR | Red Light Running | Traffic signal camera correlation |
| ILT | Illegal Turn | ANPR + geofence rule matching |
| BUS | Bus Lane Violation | ANPR in bus lane zones |
| CON | Congestion Charge Evasion | ANPR in charging zone without payment |
| INS | No Insurance | ANPR + MID (Motor Insurance Database) lookup |

## Inputs
- Normalized traffic events from Redis Streams (output of ingestion)
- Speed limit data from `config/speed_limits.yaml` or PostGIS spatial lookup
- Zone definitions from PostGIS (bus lanes, congestion zones, turn restrictions)

## Execution Scripts
- `execution/detect_speed_violation.py` - Compare observed speed vs limit
- `execution/detect_zone_violation.py` - Check ANPR hits against zone rules
- `execution/lookup_vehicle.py` - DVLA/MID vehicle and insurance checks

## Output
- Violation records written to `violations` Redis Stream
- Schema: see `src/models/violation.py`

## Edge Cases
- **Ambiguous readings**: Flag for manual review if confidence < threshold
- **Emergency vehicles**: Cross-reference against emergency vehicle registry; exempt
- **Temporary speed limits**: Check for active roadworks/variable speed limit orders
- **Data lag**: If camera timestamp is >5 min stale, log warning and still process but flag as delayed

## Processing Rules
1. Every event must be processed within 5 seconds of receipt
2. Violations must include: vehicle ID (plate), location, timestamp, violation type, evidence reference
3. Duplicate violations for the same vehicle + location within 60 seconds are merged
