import '../core/json_utils.dart';

/// `GET /fleet/vehicles` item (`VehicleOut`).
class Vehicle {
  const Vehicle({
    required this.id,
    required this.orgId,
    required this.fleetId,
    required this.plate,
    required this.make,
    required this.model,
    required this.axleConfig,
    required this.classCode,
    required this.tareKg,
    required this.maxGvmKg,
    required this.payloadCapacityKg,
    required this.bodyType,
    required this.status,
    required this.rfidEpcs,
    required this.lastLat,
    required this.lastLon,
    required this.lastSeenAt,
    required this.watchlisted,
    required this.raw,
  });

  factory Vehicle.fromJson(Map<String, dynamic> j) => Vehicle(
        id: asString(j['id']) ?? '',
        orgId: asString(j['org_id']) ?? '',
        fleetId: asString(j['fleet_id']),
        plate: asString(j['plate']) ?? '',
        make: asString(j['make']),
        model: asString(j['model']),
        axleConfig: asString(j['axle_config']) ?? '',
        classCode: asString(j['class_code']) ?? '',
        tareKg: asInt(j['tare_kg']) ?? 0,
        maxGvmKg: asInt(j['max_gvm_kg']) ?? 0,
        payloadCapacityKg: asInt(j['payload_capacity_kg']) ?? 0,
        bodyType: asString(j['body_type']) ?? '',
        status: asString(j['status']) ?? '',
        rfidEpcs: asStringList(j['rfid_epcs']),
        lastLat: asDouble(j['last_lat']),
        lastLon: asDouble(j['last_lon']),
        lastSeenAt: parseUtc(j['last_seen_at']),
        watchlisted: asBool(j['watchlisted']),
        raw: j,
      );

  final String id;
  final String orgId;
  final String? fleetId;
  final String plate;
  final String? make;
  final String? model;
  final String axleConfig;
  final String classCode;
  final int tareKg;
  final int maxGvmKg;
  final int payloadCapacityKg;
  final String bodyType;
  final String status;
  final List<String> rfidEpcs;
  final double? lastLat;
  final double? lastLon;
  final DateTime? lastSeenAt;
  final bool watchlisted;
  final Map<String, dynamic> raw;

  String get label =>
      [make, model].where((e) => e != null && e.isNotEmpty).join(' ');
}
