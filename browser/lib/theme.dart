import 'package:flutter/material.dart';

class AppTheme {
  static ThemeData get lightTheme {
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.light,
      colorScheme: const ColorScheme.light(
        primary: Color(0xFF1A73E8), // Google Chrome-like blue
        surface: Color(0xFFF1F3F4), // Light gray background for chrome
        surfaceContainerHighest: Colors.white,
        onSurface: Color(0xFF202124),
      ),
      scaffoldBackgroundColor: const Color(0xFFF1F3F4),
      appBarTheme: const AppBarTheme(
        backgroundColor: Color(0xFFF1F3F4),
        elevation: 0,
        scrolledUnderElevation: 0,
        iconTheme: IconThemeData(color: Color(0xFF5F6368)),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: Colors.white,
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(24),
          borderSide: BorderSide.none,
        ),
        hintStyle: const TextStyle(color: Color(0xFF80868B)),
      ),
      typography: Typography.material2021(),
    );
  }
}
