/// Typed exceptions mapped from FastAPI error responses.
///
/// FastAPI returns `{"detail": ...}` where `detail` is either a string
/// (HTTPException) or, for 422, a list of `{loc, msg, type}` objects.
library;

class ApiException implements Exception {
  ApiException(this.statusCode, this.detail, {this.raw});

  final int statusCode;

  /// Human-readable message extracted from the response `detail`.
  final String detail;
  final Object? raw;

  /// Builds the most specific exception for [statusCode].
  factory ApiException.fromResponse(int statusCode, Object? body) {
    final detail = extractDetail(body);
    switch (statusCode) {
      case 401:
        return UnauthorizedException(detail, raw: body);
      case 403:
        return ForbiddenException(detail, raw: body);
      case 404:
        return NotFoundException(detail, raw: body);
      case 409:
        return ConflictException(detail, raw: body);
      case 422:
        return ValidationException(detail,
            errors: FieldError.listFrom(body), raw: body);
      case 423:
        return LockedException(detail, raw: body);
      default:
        return ApiException(statusCode, detail, raw: body);
    }
  }

  static String extractDetail(Object? body) {
    if (body is Map && body['detail'] != null) {
      final d = body['detail'];
      if (d is String) return d;
      if (d is List) {
        return FieldError.listFrom(body).map((e) => e.toString()).join('; ');
      }
      return d.toString();
    }
    if (body is String && body.isNotEmpty) return body;
    return 'Request failed';
  }

  @override
  String toString() => 'ApiException($statusCode): $detail';
}

class UnauthorizedException extends ApiException {
  UnauthorizedException(String detail, {Object? raw})
      : super(401, detail, raw: raw);
}

class ForbiddenException extends ApiException {
  ForbiddenException(String detail, {Object? raw})
      : super(403, detail, raw: raw);
}

class NotFoundException extends ApiException {
  NotFoundException(String detail, {Object? raw})
      : super(404, detail, raw: raw);
}

class ConflictException extends ApiException {
  ConflictException(String detail, {Object? raw})
      : super(409, detail, raw: raw);
}

class LockedException extends ApiException {
  LockedException(String detail, {Object? raw}) : super(423, detail, raw: raw);
}

class ValidationException extends ApiException {
  ValidationException(String detail,
      {this.errors = const <FieldError>[], Object? raw})
      : super(422, detail, raw: raw);

  final List<FieldError> errors;

  /// Message for a specific body field (e.g. `containers.0.number`), if any.
  String? forField(String field) {
    for (final e in errors) {
      if (e.field == field || e.field.endsWith('.$field')) return e.message;
    }
    return null;
  }
}

/// No HTTP response at all: DNS, socket, TLS or timeout failure.
class NetworkException extends ApiException {
  NetworkException(String detail) : super(0, detail);
}

class FieldError {
  const FieldError(this.field, this.message);
  final String field;
  final String message;

  static List<FieldError> listFrom(Object? body) {
    if (body is! Map || body['detail'] is! List) return const [];
    final out = <FieldError>[];
    for (final item in body['detail'] as List) {
      if (item is! Map) continue;
      final loc = (item['loc'] is List)
          ? (item['loc'] as List).skip(1).map((e) => e.toString()).join('.')
          : '';
      out.add(FieldError(loc, item['msg']?.toString() ?? 'invalid'));
    }
    return out;
  }

  @override
  String toString() => field.isEmpty ? message : '$field: $message';
}
