import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'main_screen.dart';
import 'screens/login_screen.dart';
import 'services/auth_service.dart';
import 'services/network_spider.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await AuthService.init();
  await NetworkSpider.init();
  final hasAccount = await AuthService.hasAccount();
  
  runApp(FeedoSocialApp(hasAccount: hasAccount));
}

class FeedoSocialApp extends StatelessWidget {
  final bool hasAccount;
  const FeedoSocialApp({super.key, required this.hasAccount});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Feedo',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: const Color(0xFF0F172A), // Slate 900 base
        primaryColor: const Color(0xFF6366F1), // Indigo
        colorScheme: ColorScheme.dark(
          primary: Color(0xFF6366F1),
          secondary: Color(0xFF0EA5E9), // Sky blue
          surface: Color(0xFF1E293B), // Slate 800
          background: Color(0xFF0F172A),
        ),
        textTheme: GoogleFonts.interTextTheme(
          ThemeData.dark().textTheme,
        ),
        appBarTheme: const AppBarTheme(
          backgroundColor: const Color(0xFF0F172A),
          foregroundColor: Colors.white,
          elevation: 0,
        ),
        useMaterial3: true,
      ),
      home: hasAccount ? const MainScreen() : const LoginScreen(),
    );
  }
}
