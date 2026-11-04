import '../core/json_utils.dart';

/// `GET /notifications` item (`NotificationOut`).
class AppNotification {
  const AppNotification({
    required this.id,
    required this.channel,
    required this.template,
    required this.title,
    required this.body,
    required this.payload,
    required this.status,
    required this.createdAt,
    required this.readAt,
    required this.raw,
  });

  factory AppNotification.fromJson(Map<String, dynamic> j) => AppNotification(
        id: asString(j['id']) ?? '',
        channel: asString(j['channel']) ?? '',
        template: asString(j['template']) ?? '',
        title: asString(j['title']) ?? '',
        body: asString(j['body']) ?? '',
        payload: asMap(j['payload']),
        status: asString(j['status']) ?? '',
        createdAt: parseUtc(j['created_at']),
        readAt: parseUtc(j['read_at']),
        raw: j,
      );

  final String id;

  /// `ws | sms | email`
  final String channel;
  final String template;
  final String title;
  final String body;
  final Map<String, dynamic> payload;
  final String status;
  final DateTime? createdAt;
  final DateTime? readAt;
  final Map<String, dynamic> raw;

  bool get isRead => readAt != null;

  AppNotification markedRead() => AppNotification(
        id: id,
        channel: channel,
        template: template,
        title: title,
        body: body,
        payload: payload,
        status: status,
        createdAt: createdAt,
        readAt: DateTime.now().toUtc(),
        raw: {...raw, 'read_at': DateTime.now().toUtc().toIso8601String()},
      );
}
