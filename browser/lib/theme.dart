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

  static ThemeData get darkTheme {
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      colorScheme: const ColorScheme.dark(
        primary: Color(0xFF4C82F6), // Vibrant blue accent
        surface: Color(0xFF1E1E1E), // Deep dark gray for background
        surfaceContainerHighest: Color(0xFF2D2D2D), // Elevated dark gray
        onSurface: Color(0xFFE0E0E0), // Clean light gray text
        secondary: Color(0xFF9AA0A6),
      ),
      scaffoldBackgroundColor: const Color(0xFF1E1E1E),
      appBarTheme: const AppBarTheme(
        backgroundColor: Color(0xFF1E1E1E),
        elevation: 0,
        scrolledUnderElevation: 0,
        iconTheme: IconThemeData(color: Color(0xFFE0E0E0)),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: const Color(0xFF2D2D2D),
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(24),
          borderSide: BorderSide.none,
        ),
        hintStyle: const TextStyle(color: Color(0xFF9AA0A6)),
      ),
      typography: Typography.material2021(),
    );
  }
}
