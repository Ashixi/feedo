import 'package:flutter/material.dart';

class FeedLayout extends StatelessWidget {
  final Widget child;
  const FeedLayout({super.key, required this.child});

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.topCenter,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 600),
        child: child,
      ),
    );
  }
}
