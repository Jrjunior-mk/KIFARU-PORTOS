import '../core/json_utils.dart';

/// `POST /auth/login`, `/auth/refresh` response (`TokenOut`).
class Token {
  const Token({
    required this.accessToken,
    required this.refreshToken,
    required this.tokenType,
    required this.expiresIn,
    required this.mfaRequired,
    required this.roles,
    required this.orgId,
    required this.userId,
    required this.fullName,
  });

  factory Token.fromJson(Map<String, dynamic> j) => Token(
        accessToken: asString(j['access_token']) ?? '',
        refreshToken: asString(j['refresh_token']) ?? '',
        tokenType: asString(j['token_type']) ?? 'bearer',
        expiresIn: asInt(j['expires_in']) ?? 900,
        mfaRequired: asBool(j['mfa_required']),
        roles: asStringList(j['roles']),
        orgId: asString(j['org_id']),
        userId: asString(j['user_id']) ?? '',
        fullName: asString(j['full_name']) ?? '',
      );

  final String accessToken;
  final String refreshToken;
  final String tokenType;
  final int expiresIn;
  final bool mfaRequired;
  final List<String> roles;
  final String? orgId;
  final String userId;
  final String fullName;
}
