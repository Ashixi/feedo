import 'package:flutter/material.dart';

class FeedFilterConfig {
  final String keywords;
  final String language;
  final DateTime? since;
  final DateTime? until;

  FeedFilterConfig({
    this.keywords = '',
    this.language = 'all',
    this.since,
    this.until,
  });

  FeedFilterConfig copyWith({
    String? keywords,
    String? language,
    DateTime? since,
    DateTime? until,
    bool clearSince = false,
    bool clearUntil = false,
  }) {
    return FeedFilterConfig(
      keywords: keywords ?? this.keywords,
      language: language ?? this.language,
      since: clearSince ? null : (since ?? this.since),
      until: clearUntil ? null : (until ?? this.until),
    );
  }

  bool get isEmpty => keywords.isEmpty && language == 'all' && since == null && until == null;
}

final ValueNotifier<FeedFilterConfig> globalFeedFilter = ValueNotifier(FeedFilterConfig());
