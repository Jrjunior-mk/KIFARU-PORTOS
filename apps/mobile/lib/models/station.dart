import '../core/json_utils.dart';

class Lane {
  const Lane({
    required this.id,
    required this.laneNo,
    required this.type,
    required this.direction,
    required this.status,
  });

  factory Lane.fromJson(Map<String, dynamic> j) => Lane(
        id: asString(j['id']) ?? '',
        laneNo: asInt(j['lane_no']) ?? 0,
        type: asString(j['type']) ?? '',
        direction: asString(j['direction']) ?? '',
        status: asString(j['status']) ?? '',
      );

  final String id;
  final int laneNo;

  /// `wim_highspeed | wim_lowspeed | static`
  final String type;
  final String direction;
  final String status;
}

/// `GET /stations` item (`StationOut`), including the latest observed queue.
class Station {
  const Station({
    required this.id,
    required this.code,
    required this.name,
    required this.lat,
    required this.lon,
    required this.capacityPerHour,
    required this.staticCapacityPerHour,
    required this.altAllowed,
    required this.status,
    required this.lanes,
    required this.queueLen,
    required this.avgWaitS,
    required this.utilisation,
    required this.decisionsLastHour,
    required this.raw,
  });

  factory Station.fromJson(Map<String, dynamic> j) => Station(
        id: asString(j['id']) ?? '',
        code: asString(j['code']) ?? '',
        name: asString(j['name']) ?? '',
        lat: asDouble(j['lat']) ?? 0,
        lon: asDouble(j['lon']) ?? 0,
        capacityPerHour: asInt(j['capacity_per_hour']) ?? 0,
        staticCapacityPerHour: asInt(j['static_capacity_per_hour']) ?? 0,
        altAllowed: asBool(j['alt_allowed']),
        status: asString(j['status']) ?? '',
        lanes: asMapList(j['lanes']).map(Lane.fromJson).toList(),
        queueLen: asInt(j['queue_len']) ?? 0,
        avgWaitS: asInt(j['avg_wait_s']) ?? 0,
        utilisation: asDouble(j['utilisation']) ?? 0,
        decisionsLastHour: asMap(j['decisions_last_hour'])
            .map((k, v) => MapEntry(k, asInt(v) ?? 0)),
        raw: j,
      );

  final String id;
  final String code;
  final String name;
  final double lat;
  final double lon;
  final int capacityPerHour;
  final int staticCapacityPerHour;
  final bool altAllowed;

  /// `operational | degraded | offline`
  final String status;
  final List<Lane> lanes;
  final int queueLen;
  final int avgWaitS;
  final double utilisation;
  final Map<String, int> decisionsLastHour;
  final Map<String, dynamic> raw;

  /// Lane number of the first static-scale lane, used in the AMBER
  /// instruction ("Proceed to static scale - lane N").
  int? get staticLaneNo {
    for (final l in lanes) {
      if (l.type == 'static') return l.laneNo;
    }
    return null;
  }

  Station withQueue({required int queueLen, required int avgWaitS}) => Station(
        id: id,
        code: code,
        name: name,
        lat: lat,
        lon: lon,
        capacityPerHour: capacityPerHour,
        staticCapacityPerHour: staticCapacityPerHour,
        altAllowed: altAllowed,
        status: status,
        lanes: lanes,
        queueLen: queueLen,
        avgWaitS: avgWaitS,
        utilisation: utilisation,
        decisionsLastHour: decisionsLastHour,
        raw: {...raw, 'queue_len': queueLen, 'avg_wait_s': avgWaitS},
      );
}

/// `GET /queue/{station}/slots` item (`SlotOut`).
class Slot {
  const Slot({
    required this.slotStart,
    required this.slotEnd,
    required this.capacity,
    required this.booked,
    required this.available,
  });

  factory Slot.fromJson(Map<String, dynamic> j) => Slot(
        slotStart: parseUtc(j['slot_start']) ?? DateTime.now().toUtc(),
        slotEnd: parseUtc(j['slot_end']) ?? DateTime.now().toUtc(),
        capacity: asInt(j['capacity']) ?? 0,
        booked: asInt(j['booked']) ?? 0,
        available: asInt(j['available']) ?? 0,
      );

  final DateTime slotStart;
  final DateTime slotEnd;
  final int capacity;
  final int booked;
  final int available;
}
