import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import '../utils/bech32.dart';
import '../screens/user_profile_screen.dart';
import 'quoted_event_card.dart';

class LinkifiedText extends StatelessWidget {
  final String text;
  final TextStyle? style;
  final TextStyle? linkStyle;
  final int? maxLines;
  final TextOverflow? overflow;
  final TextAlign textAlign;

  const LinkifiedText({
    super.key,
    required this.text,
    this.style,
    this.linkStyle,
    this.maxLines,
    this.overflow,
    this.textAlign = TextAlign.start,
  });

  @override
  Widget build(BuildContext context) {
    final defaultStyle = style ?? const TextStyle(color: Colors.black87, fontSize: 15);
    final anchorStyle = linkStyle ?? TextStyle(color: Theme.of(context).colorScheme.primary, decoration: TextDecoration.underline);

    // Regex for URLs and nostr links
    final urlRegex = RegExp(
      r'(https?:\/\/[^\s]+)|(nostr:(npub1[a-z0-9]+|nprofile1[a-z0-9]+|nevent1[a-z0-9]+|note1[a-z0-9]+|naddr1[a-z0-9]+))|(npub1[a-z0-9]+|nprofile1[a-z0-9]+|nevent1[a-z0-9]+|note1[a-z0-9]+|naddr1[a-z0-9]+)',
      caseSensitive: false,
    );

    final matches = urlRegex.allMatches(text);
    if (matches.isEmpty) {
      return Text(text, style: defaultStyle);
    }

    List<InlineSpan> spans = [];
    int currentPosition = 0;

    for (final match in matches) {
      if (match.start > currentPosition) {
        spans.add(TextSpan(
          text: text.substring(currentPosition, match.start),
          style: defaultStyle,
        ));
      }

      final matchedText = match.group(0)!;
      final isNostr = matchedText.startsWith('nostr:') || 
                      matchedText.startsWith('npub') || 
                      matchedText.startsWith('nprofile') ||
                      matchedText.startsWith('nevent') ||
                      matchedText.startsWith('note') ||
                      matchedText.startsWith('naddr');

      if (isNostr) {
        if (matchedText.contains('npub') || matchedText.contains('nprofile')) {
          final clean = matchedText.replaceAll('nostr:', '');
          final displayText = '@${clean.substring(0, 10)}...';
          spans.add(TextSpan(
            text: displayText,
            style: anchorStyle,
            recognizer: TapGestureRecognizer()
              ..onTap = () async {
                final profile = Bech32.decodeProfile(matchedText);
                if (profile.pubkey.isNotEmpty && profile.pubkey.length == 64) {
                  Navigator.of(context).push(MaterialPageRoute(
                    builder: (context) => UserProfileScreen(
                      pubkey: profile.pubkey,
                      initialRelays: profile.relays,
                    ),
                  ));
                } else {
                  ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Invalid Nostr profile link')));
                }
              },
          ));
        } else {
          final eventData = Bech32.decodeEvent(matchedText);
          if (eventData.eventId.isNotEmpty) {
            spans.add(const TextSpan(text: '\n'));
            spans.add(WidgetSpan(
              child: QuotedEventCard(eventId: eventData.eventId),
            ));
            spans.add(const TextSpan(text: '\n'));
          } else {
            spans.add(TextSpan(
              text: matchedText,
              style: defaultStyle,
            ));
          }
        }
      } else {
        spans.add(TextSpan(
          text: matchedText,
          style: anchorStyle,
          recognizer: TapGestureRecognizer()
            ..onTap = () async {
              final url = Uri.parse(matchedText);
              if (await canLaunchUrl(url)) {
                await launchUrl(url);
              }
            },
        ));
      }

      currentPosition = match.end;
    }

    if (currentPosition < text.length) {
      spans.add(TextSpan(
        text: text.substring(currentPosition),
        style: defaultStyle,
      ));
    }

    return RichText(
      maxLines: maxLines,
      overflow: overflow ?? TextOverflow.clip,
      textAlign: textAlign,
      text: TextSpan(children: spans),
    );
  }
}
