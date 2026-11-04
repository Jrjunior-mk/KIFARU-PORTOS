import '../core/json_utils.dart';

/// `GET /queue/appointments/mine` item (`AppointmentOut`).
class Appointment {
  const Appointment({
    required this.id,
    required this.stationId,
    required this.stationCode,
    required this.vehicleId,
    required this.plate,
    required this.shipmentId,
    required this.slotStart,
    required this.slotEnd,
    required this.status,
    required this.priority,
    required this.estWaitS,
    required this.assignedBy,
    required this.raw,
  });

  factory Appointment.fromJson(Map<String, dynamic> j) => Appointment(
        id: asString(j['id']) ?? '',
        stationId: asString(j['station_id']) ?? '',
        stationCode: asString(j['station_code']) ?? '',
        vehicleId: asString(j['vehicle_id']) ?? '',
        plate: asString(j['plate']) ?? '',
        shipmentId: asString(j['shipment_id']),
        slotStart: parseUtc(j['slot_start']) ?? DateTime.now().toUtc(),
        slotEnd: parseUtc(j['slot_end']) ?? DateTime.now().toUtc(),
        status: asString(j['status']) ?? '',
        priority: asInt(j['priority']) ?? 5,
        estWaitS: asInt(j['est_wait_s']),
        assignedBy: asString(j['assigned_by']) ?? '',
        raw: j,
      );

  final String id;
  final String stationId;
  final String stationCode;
  final String vehicleId;
  final String plate;
  final String? shipmentId;
  final DateTime slotStart;
  final DateTime slotEnd;

  /// `booked | arrived | completed | missed | cancelled`
  final String status;
  final int priority;
  final int? estWaitS;
  final String assignedBy;
  final Map<String, dynamic> raw;

  bool get isActive => status == 'booked' || status == 'arrived';
}
