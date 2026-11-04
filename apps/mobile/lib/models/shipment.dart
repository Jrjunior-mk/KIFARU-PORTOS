import '../core/json_utils.dart';

/// Stage machine mirrored from `apps/api/kifaru/models/shipments.py`.
const List<String> kShipmentStages = [
  'registered',
  'declared',
  'at_port',
  'customs_processing',
  'weighing_verification',
  'gate_processing',
  'released',
  'in_transit',
  'delivered',
  'closed',
];

class ProcessingEvent {
  const ProcessingEvent({
    required this.id,
    required this.stage,
    required this.status,
    required this.occurredAt,
    required this.source,
    required this.notes,
  });

  factory ProcessingEvent.fromJson(Map<String, dynamic> j) => ProcessingEvent(
        id: asString(j['id']) ?? '',
        stage: asString(j['stage']) ?? '',
        status: asString(j['status']) ?? '',
        occurredAt: parseUtc(j['occurred_at']),
        source: asString(j['source']) ?? '',
        notes: asString(j['notes']),
      );

  final String id;
  final String stage;
  final String status;
  final DateTime? occurredAt;
  final String source;
  final String? notes;
}

/// Entry of `PassportOut.weighings`.
class PassportWeighing {
  const PassportWeighing({
    required this.id,
    required this.occurredAt,
    required this.gvmKg,
    required this.uKg,
    required this.decision,
    required this.stationId,
    required this.source,
  });

  factory PassportWeighing.fromJson(Map<String, dynamic> j) => PassportWeighing(
        id: asString(j['id']) ?? '',
        occurredAt: parseUtc(j['occurred_at']),
        gvmKg: asInt(j['gvm_kg']) ?? 0,
        uKg: asInt(j['u_kg']) ?? 0,
        decision: asString(j['decision']),
        stationId: asString(j['station_id']) ?? '',
        source: asString(j['source']) ?? 'unknown',
      );

  final String id;
  final DateTime? occurredAt;
  final int gvmKg;
  final int uKg;
  final String? decision;
  final String stationId;
  final String source;
}

/// Entry of `PassportOut.tickets`.
class PassportTicket {
  const PassportTicket({
    required this.id,
    required this.type,
    required this.qrToken,
    required this.decision,
    required this.gvmKg,
    required this.source,
  });

  factory PassportTicket.fromJson(Map<String, dynamic> j) => PassportTicket(
        id: asString(j['id']) ?? '',
        type: asString(j['type']) ?? '',
        qrToken: asString(j['qr_token']) ?? '',
        decision: asString(j['decision']),
        gvmKg: asInt(j['gvm_kg']) ?? 0,
        source: asString(j['source']) ?? 'unknown',
      );

  final String id;

  /// `prescreen | static_certified`
  final String type;
  final String qrToken;
  final String? decision;
  final int gvmKg;
  final String source;
}

/// Digital Cargo Passport (`PassportOut`) - `GET/POST /shipments`.
class ShipmentPassport {
  const ShipmentPassport({
    required this.id,
    required this.reference,
    required this.ownerOrgId,
    required this.ownerOrgName,
    required this.transporterOrgId,
    required this.transporterOrgName,
    required this.vehicleId,
    required this.vehiclePlate,
    required this.vehicleRfid,
    required this.warehouseId,
    required this.description,
    required this.cargoType,
    required this.origin,
    required this.destination,
    required this.declaredMassKg,
    required this.vgmKg,
    required this.stage,
    required this.status,
    required this.containers,
    required this.declaration,
    required this.seals,
    required this.processingEvents,
    required this.weighings,
    required this.tickets,
    required this.predictedReleaseAt,
    required this.predictedReleaseP10,
    required this.predictedReleaseP90,
    required this.predictionExplanation,
    required this.outstanding,
    required this.createdAt,
    required this.raw,
  });

  factory ShipmentPassport.fromJson(Map<String, dynamic> j) => ShipmentPassport(
        id: asString(j['id']) ?? '',
        reference: asString(j['reference']) ?? '',
        ownerOrgId: asString(j['owner_org_id']) ?? '',
        ownerOrgName: asString(j['owner_org_name']),
        transporterOrgId: asString(j['transporter_org_id']),
        transporterOrgName: asString(j['transporter_org_name']),
        vehicleId: asString(j['vehicle_id']),
        vehiclePlate: asString(j['vehicle_plate']),
        vehicleRfid: asStringList(j['vehicle_rfid']),
        warehouseId: asString(j['warehouse_id']),
        description: asString(j['description']) ?? '',
        cargoType: asString(j['cargo_type']) ?? 'general',
        origin: asString(j['origin']) ?? '',
        destination: asString(j['destination']) ?? '',
        declaredMassKg: asInt(j['declared_mass_kg']) ?? 0,
        vgmKg: asInt(j['vgm_kg']),
        stage: asString(j['stage']) ?? 'registered',
        status: asString(j['status']) ?? '',
        containers: asMapList(j['containers']),
        declaration: j['declaration'] is Map ? asMap(j['declaration']) : null,
        seals: asMapList(j['seals']),
        processingEvents:
            asMapList(j['processing_events']).map(ProcessingEvent.fromJson).toList(),
        weighings: asMapList(j['weighings']).map(PassportWeighing.fromJson).toList(),
        tickets: asMapList(j['tickets']).map(PassportTicket.fromJson).toList(),
        predictedReleaseAt: parseUtc(j['predicted_release_at']),
        predictedReleaseP10: parseUtc(j['predicted_release_p10']),
        predictedReleaseP90: parseUtc(j['predicted_release_p90']),
        predictionExplanation: j['prediction_explanation'] is Map
            ? asMap(j['prediction_explanation'])
            : null,
        outstanding: asStringList(j['outstanding']),
        createdAt: parseUtc(j['created_at']),
        raw: j,
      );

  final String id;
  final String reference;
  final String ownerOrgId;
  final String? ownerOrgName;
  final String? transporterOrgId;
  final String? transporterOrgName;
  final String? vehicleId;
  final String? vehiclePlate;
  final List<String> vehicleRfid;
  final String? warehouseId;
  final String description;
  final String cargoType;
  final String origin;
  final String destination;
  final int declaredMassKg;
  final int? vgmKg;
  final String stage;
  final String status;
  final List<Map<String, dynamic>> containers;
  final Map<String, dynamic>? declaration;
  final List<Map<String, dynamic>> seals;
  final List<ProcessingEvent> processingEvents;
  final List<PassportWeighing> weighings;
  final List<PassportTicket> tickets;
  final DateTime? predictedReleaseAt;
  final DateTime? predictedReleaseP10;
  final DateTime? predictedReleaseP90;
  final Map<String, dynamic>? predictionExplanation;
  final List<String> outstanding;
  final DateTime? createdAt;
  final Map<String, dynamic> raw;

  int get stageIndex {
    final i = kShipmentStages.indexOf(stage);
    return i < 0 ? 0 : i;
  }
}
