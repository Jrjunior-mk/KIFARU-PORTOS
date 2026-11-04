import '../core/json_utils.dart';

/// Public `GET /tickets/verify/{qr_token}` (`VerifyOut`). Unauthenticated;
/// contains only non-sensitive fields.
class TicketVerification {
  const TicketVerification({
    required this.valid,
    required this.ticketType,
    required this.legalStatus,
    required this.plate,
    required this.gvmKg,
    required this.decision,
    required this.occurredAt,
    required this.station,
    required this.source,
    required this.evidenceHash,
  });

  factory TicketVerification.fromJson(Map<String, dynamic> j) =>
      TicketVerification(
        valid: asBool(j['valid']),
        ticketType: asString(j['ticket_type']),
        legalStatus: asString(j['legal_status']),
        plate: asString(j['plate']),
        gvmKg: asInt(j['gvm_kg']),
        decision: asString(j['decision']),
        occurredAt: parseUtc(j['occurred_at']),
        station: asString(j['station']),
        source: asString(j['source']),
        evidenceHash: asString(j['evidence_hash']),
      );

  final bool valid;
  final String? ticketType;
  final String? legalStatus;
  final String? plate;
  final int? gvmKg;
  final String? decision;
  final DateTime? occurredAt;
  final String? station;
  final String? source;
  final String? evidenceHash;
}
