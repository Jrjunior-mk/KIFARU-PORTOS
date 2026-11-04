import '../core/json_utils.dart';

class Axle {
  const Axle({
    required this.axleIndex,
    required this.loadKg,
    required this.uncertaintyKg,
    required this.spacingToNextM,
    required this.groupNo,
  });

  factory Axle.fromJson(Map<String, dynamic> j) => Axle(
        axleIndex: asInt(j['axle_index']) ?? 0,
        loadKg: asInt(j['load_kg']) ?? 0,
        uncertaintyKg: asInt(j['uncertainty_kg']) ?? 0,
        spacingToNextM: asDouble(j['spacing_to_next_m']),
        groupNo: asInt(j['group_no']) ?? 0,
      );

  final int axleIndex;
  final int loadKg;
  final int uncertaintyKg;
  final double? spacingToNextM;
  final int groupNo;
}

class Identity {
  const Identity({
    required this.anprPlate,
    required this.anprConfidence,
    required this.rfidEpc,
    required this.rfidConfidence,
    required this.confidence,
    required this.method,
    required this.explanation,
  });

  factory Identity.fromJson(Map<String, dynamic> j) => Identity(
        anprPlate: asString(j['anpr_plate']),
        anprConfidence: asDouble(j['anpr_confidence']),
        rfidEpc: asString(j['rfid_epc']),
        rfidConfidence: asDouble(j['rfid_confidence']),
        confidence: asDouble(j['confidence']) ?? 0,
        method: asString(j['method']) ?? '',
        explanation: asString(j['explanation']),
      );

  final String? anprPlate;
  final double? anprConfidence;
  final String? rfidEpc;
  final double? rfidConfidence;
  final double confidence;
  final String method;
  final String? explanation;
}

/// `DecisionOut`: the deterministic clearance decision for one pass.
class Decision {
  const Decision({
    required this.id,
    required this.decision,
    required this.rulesFired,
    required this.margins,
    required this.limitsVersion,
    required this.engineVersion,
    required this.auditSelected,
    required this.evidenceHash,
    required this.decidedAt,
    required this.latencyMs,
    required this.explanation,
    required this.staticVerifiedGvmKg,
    required this.overrideReason,
    required this.ticketId,
    required this.ticketType,
    required this.qrToken,
  });

  factory Decision.fromJson(Map<String, dynamic> j) => Decision(
        id: asString(j['id']) ?? '',
        decision: (asString(j['decision']) ?? '').toUpperCase(),
        rulesFired: asList(j['rules_fired']),
        margins: asMap(j['margins']),
        limitsVersion: asString(j['limits_version']) ?? '',
        engineVersion: asString(j['engine_version']) ?? '',
        auditSelected: asBool(j['audit_selected']),
        evidenceHash: asString(j['evidence_hash']) ?? '',
        decidedAt: parseUtc(j['decided_at']),
        latencyMs: asInt(j['latency_ms']) ?? 0,
        explanation: asString(j['explanation']) ?? '',
        staticVerifiedGvmKg: asInt(j['static_verified_gvm_kg']),
        overrideReason: asString(j['override_reason']),
        ticketId: asString(j['ticket_id']),
        ticketType: asString(j['ticket_type']),
        qrToken: asString(j['qr_token']),
      );

  final String id;

  /// `GREEN | AMBER | RED`
  final String decision;

  /// List of `{rule, severity, detail}` maps (or plain rule codes).
  final List<dynamic> rulesFired;
  final Map<String, dynamic> margins;
  final String limitsVersion;
  final String engineVersion;
  final bool auditSelected;
  final String evidenceHash;
  final DateTime? decidedAt;
  final int latencyMs;
  final String explanation;
  final int? staticVerifiedGvmKg;
  final String? overrideReason;
  final String? ticketId;

  /// `prescreen | static_certified`
  final String? ticketType;
  final String? qrToken;

  List<String> get ruleCodes => rulesFired.map((r) {
        if (r is Map) return asString(r['rule']) ?? r.toString();
        return r.toString();
      }).toList();
}

/// `GET /weighing/events` item (`WeighingOut`).
class WeighingEvent {
  const WeighingEvent({
    required this.id,
    required this.stationId,
    required this.laneId,
    required this.vehicleId,
    required this.plate,
    required this.shipmentId,
    required this.occurredAt,
    required this.speedMps,
    required this.gvmKg,
    required this.gvmUncertaintyKg,
    required this.axleCount,
    required this.detectedAxleConfig,
    required this.classCode,
    required this.qualityFlags,
    required this.sensorHealth,
    required this.pavementTempC,
    required this.source,
    required this.kind,
    required this.axles,
    required this.identity,
    required this.decision,
    required this.raw,
  });

  factory WeighingEvent.fromJson(Map<String, dynamic> j) => WeighingEvent(
        id: asString(j['id']) ?? '',
        stationId: asString(j['station_id']) ?? '',
        laneId: asString(j['lane_id']) ?? '',
        vehicleId: asString(j['vehicle_id']),
        plate: asString(j['plate']),
        shipmentId: asString(j['shipment_id']),
        occurredAt: parseUtc(j['occurred_at']),
        speedMps: asDouble(j['speed_mps']) ?? 0,
        gvmKg: asInt(j['gvm_kg']) ?? 0,
        gvmUncertaintyKg: asInt(j['gvm_uncertainty_kg']) ?? 0,
        axleCount: asInt(j['axle_count']) ?? 0,
        detectedAxleConfig: asString(j['detected_axle_config']),
        classCode: asString(j['class_code']),
        qualityFlags: asStringList(j['quality_flags']),
        sensorHealth: asMap(j['sensor_health']),
        pavementTempC: asDouble(j['pavement_temp_c']),
        source: asString(j['source']) ?? 'unknown',
        kind: asString(j['kind']) ?? '',
        axles: asMapList(j['axles']).map(Axle.fromJson).toList(),
        identity:
            j['identity'] is Map ? Identity.fromJson(asMap(j['identity'])) : null,
        decision:
            j['decision'] is Map ? Decision.fromJson(asMap(j['decision'])) : null,
        raw: j,
      );

  final String id;
  final String stationId;
  final String laneId;
  final String? vehicleId;
  final String? plate;
  final String? shipmentId;
  final DateTime? occurredAt;
  final double speedMps;
  final int gvmKg;
  final int gvmUncertaintyKg;
  final int axleCount;
  final String? detectedAxleConfig;
  final String? classCode;
  final List<String> qualityFlags;
  final Map<String, dynamic> sensorHealth;
  final double? pavementTempC;

  /// `live | simulated | replay` - always shown to the user as a badge.
  final String source;
  final String kind;
  final List<Axle> axles;
  final Identity? identity;
  final Decision? decision;
  final Map<String, dynamic> raw;

  double get gvmTonnes => gvmKg / 1000.0;
}
