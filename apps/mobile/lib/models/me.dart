import '../core/json_utils.dart';

/// `GET /auth/me` (`MeOut`).
class Me {
  const Me({
    required this.userId,
    required this.email,
    required this.fullName,
    required this.roles,
    required this.orgId,
    required this.orgName,
    required this.orgType,
    required this.mfaEnabled,
    required this.mfaVerified,
    required this.raw,
  });

  factory Me.fromJson(Map<String, dynamic> j) => Me(
        userId: asString(j['user_id']) ?? '',
        email: asString(j['email']) ?? '',
        fullName: asString(j['full_name']) ?? '',
        roles: asStringList(j['roles']),
        orgId: asString(j['org_id']),
        orgName: asString(j['org_name']),
        orgType: asString(j['org_type']),
        mfaEnabled: asBool(j['mfa_enabled']),
        mfaVerified: asBool(j['mfa_verified']),
        raw: j,
      );

  final String userId;
  final String email;
  final String fullName;
  final List<String> roles;
  final String? orgId;
  final String? orgName;
  final String? orgType;
  final bool mfaEnabled;
  final bool mfaVerified;
  final Map<String, dynamic> raw;

  bool hasRole(String role) => roles.contains(role);
  bool get isDriver => hasRole('driver');
  bool get isCargoOwner => hasRole('cargo_owner');

  /// Transporter staff may also use the driver flow (they can book slots and
  /// post positions per the fleet router's role lists).
  bool get canUseDriverFlow =>
      isDriver || hasRole('transporter_admin') || hasRole('dispatcher');
}
