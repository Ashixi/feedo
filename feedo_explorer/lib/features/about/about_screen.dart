import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'about_content.dart';

class AboutScreen extends StatelessWidget {
  const AboutScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 1000),
          child: Markdown(
            data: aboutProjectMarkdown,
            selectable: true,
            styleSheet: MarkdownStyleSheet(
              h1: const TextStyle(fontSize: 32, fontWeight: FontWeight.bold, color: Colors.white, height: 1.5),
              h2: const TextStyle(fontSize: 24, fontWeight: FontWeight.bold, color: Color(0xFFC05640), height: 2),
              h3: const TextStyle(fontSize: 20, fontWeight: FontWeight.w600, color: Colors.white70, height: 1.8),
              p: const TextStyle(fontSize: 16, height: 1.6, color: Colors.white70),
              listBullet: const TextStyle(fontSize: 16, color: Colors.white70),
              code: TextStyle(
                backgroundColor: Colors.white.withOpacity(0.05),
                color: const Color(0xFF10B981),
                fontFamily: 'monospace',
                fontSize: 14,
              ),
              codeblockDecoration: BoxDecoration(
                color: const Color(0xFF1a1613),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: const Color(0xFFC05640).withOpacity(0.2)),
              ),
              codeblockPadding: const EdgeInsets.all(16),
              blockquoteDecoration: BoxDecoration(
                color: const Color(0xFFC05640).withOpacity(0.1),
                border: const Border(left: BorderSide(color: Color(0xFFC05640), width: 4)),
              ),
              blockquotePadding: const EdgeInsets.all(16),
              horizontalRuleDecoration: BoxDecoration(
                border: Border(top: BorderSide(color: Colors.white.withOpacity(0.1), width: 1)),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
