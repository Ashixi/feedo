import 'package:feedo_explorer/l10n/app_localizations.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';
import 'package:url_launcher/url_launcher.dart';
import 'dart:math' as math;

class DashboardScreen extends ConsumerStatefulWidget {
  const DashboardScreen({super.key});

  @override
  ConsumerState<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends ConsumerState<DashboardScreen> with SingleTickerProviderStateMixin {
  late AnimationController _pulseController;
  final GlobalKey _manifestoKey = GlobalKey();

  @override
  void initState() {
    super.initState();
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 3),
    )..repeat(reverse: true);
  }

  @override
  void dispose() {
    _pulseController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final loc = AppLocalizations.of(context)!;
    final screenWidth = MediaQuery.of(context).size.width;
    final isMobile = screenWidth < 800;

    return Scaffold(
      backgroundColor: const Color(0xFF0A0A0A),
      body: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            _buildHeroSection(isMobile, context),
            _buildExplorerQuickLinks(isMobile, context),
            _buildProblemSection(isMobile, _manifestoKey),
            _buildSolutionSection(isMobile),
            _buildTechSection(isMobile),
            _buildEcosystemSection(isMobile),
            _buildFooter(isMobile),
          ],
        ),
      ),
    );
  }

  Widget _buildHeroSection(bool isMobile, BuildContext context) {
    final loc = AppLocalizations.of(context)!;
    return Container(
      width: double.infinity,
      padding: EdgeInsets.symmetric(
        horizontal: isMobile ? 24.0 : 64.0,
        vertical: isMobile ? 64.0 : 120.0,
      ),
      decoration: BoxDecoration(
        gradient: RadialGradient(
          center: const Alignment(0, -0.5),
          radius: 1.5,
          colors: [
            const Color(0xFF1E3A8A).withOpacity(0.4),
            const Color(0xFF0A0A0A),
          ],
        ),
      ),
      child: Column(
        children: [
          AnimatedBuilder(
            animation: _pulseController,
            builder: (context, child) {
              return Transform.scale(
                scale: 1.0 + (_pulseController.value * 0.05),
                child: Container(
                  padding: const EdgeInsets.all(24),
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: Colors.blueAccent.withOpacity(0.1),
                    boxShadow: [
                      BoxShadow(
                        color: Colors.blueAccent.withOpacity(0.2 * _pulseController.value),
                        blurRadius: 30,
                        spreadRadius: 10,
                      )
                    ],
                  ),
                  child: Image.asset(
                    'assets/logo.png',
                    height: 80,
                    errorBuilder: (context, error, stackTrace) => Icon(
                      LucideIcons.boxes,
                      size: 80,
                      color: Colors.blueAccent,
                    ),
                  ),
                ),
              );
            },
          ),
          const SizedBox(height: 40),
          Text(loc.heroTitle,
            textAlign: TextAlign.center,
            style: TextStyle(
              fontSize: isMobile ? 36 : 64,
              fontWeight: FontWeight.w900,
              color: Colors.white,
              height: 1.1,
              letterSpacing: -1.5,
            ),
          ),
          const SizedBox(height: 24),
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 800),
            child: Text(loc.heroSubtitle,
              textAlign: TextAlign.center,
              style: TextStyle(
                fontSize: isMobile ? 18 : 22,
                color: Colors.white70,
                height: 1.6,
                fontWeight: FontWeight.w400,
              ),
            ),
          ),
          const SizedBox(height: 48),
          Wrap(
            spacing: 16,
            runSpacing: 16,
            alignment: WrapAlignment.center,
            children: [
              _HeroButton(
                text: loc.readManifesto,
                isPrimary: true,
                onTap: () {
                  if (_manifestoKey.currentContext != null) {
                    Scrollable.ensureVisible(
                      _manifestoKey.currentContext!,
                      duration: const Duration(milliseconds: 600),
                      curve: Curves.easeInOut,
                    );
                  }
                },
              ),
              _HeroButton(
                text: loc.documentationButton,
                isPrimary: false,
                onTap: () => context.go('/docs'),
              ),
              _HeroButton(
                text: loc.deployDapp,
                isPrimary: false,
                onTap: () async {
                  final url = Uri.parse('https://github.com/Ashixi/feedo.git');
                  if (await canLaunchUrl(url)) {
                    await launchUrl(url);
                  }
                },
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildExplorerQuickLinks(bool isMobile, BuildContext context) {
    final loc = AppLocalizations.of(context)!;
    return Container(
      width: double.infinity,
      padding: EdgeInsets.symmetric(horizontal: isMobile ? 24 : 64, vertical: 40),
      color: const Color(0xFF121212),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 1200),
          child: Column(
            children: [
              Text(loc.liveNetworkExplorer,
                style: TextStyle(
                  fontSize: 20,
                  fontWeight: FontWeight.bold,
                  color: Colors.white54,
                  letterSpacing: 1.2,
                  fontFamily: 'monospace',
                ),
              ),
              const SizedBox(height: 32),
              Wrap(
                spacing: 16,
                runSpacing: 16,
                alignment: WrapAlignment.center,
                children: [
                  _QuickLinkCard(
                    title: loc.networkTopologyTitle,
                    icon: LucideIcons.network,
                    color: Colors.blue,
                    onTap: () => context.go('/network'),
                  ),
                  _QuickLinkCard(
                    title: loc.identitiesDidTitle,
                    icon: LucideIcons.fingerprint,
                    color: Colors.purple,
                    onTap: () => context.go('/identities'),
                  ),
                  _QuickLinkCard(
                    title: loc.consensusLogsTitle,
                    icon: LucideIcons.history,
                    color: Colors.green,
                    onTap: () => context.go('/consensus'),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildProblemSection(bool isMobile, GlobalKey key) {
    final loc = AppLocalizations.of(context)!;
    return _SectionContainer(
      key: key,
      isMobile: isMobile,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SizedBox(height: 16),
          _SectionTitle(text: loc.problemTitle),
          const SizedBox(height: 24),
          _SectionBody(text: loc.problemBody),
        ],
      ),
    );
  }

  Widget _buildSolutionSection(bool isMobile) {
    final loc = AppLocalizations.of(context)!;
    return _SectionContainer(
      isMobile: isMobile,
      backgroundColor: const Color(0xFF111827), // slight dark blue tint
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SizedBox(height: 16),
          _SectionTitle(text: loc.solutionTitle),
          const SizedBox(height: 24),
          _SectionBody(text: loc.solutionBody),
        ],
      ),
    );
  }

  Widget _buildTechSection(bool isMobile) {
    final loc = AppLocalizations.of(context)!;
    return _SectionContainer(
      isMobile: isMobile,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SizedBox(height: 16),
          _SectionTitle(text: loc.techTitle),
          const SizedBox(height: 24),
          _SectionBody(text: loc.techBody),
          const SizedBox(height: 48),
          GridView.count(
            crossAxisCount: isMobile ? 1 : 2,
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            crossAxisSpacing: 24,
            mainAxisSpacing: 24,
            childAspectRatio: isMobile ? 1.5 : 2.0,
            children: [
              _TechCard(
                icon: LucideIcons.zap,
                title: loc.techRust,
                description: loc.techRustDesc,
              ),
              _TechCard(
                icon: LucideIcons.network,
                title: loc.techVector,
                description: loc.techVectorDesc,
              ),
              _TechCard(
                icon: LucideIcons.gitMerge,
                title: loc.techCrdt,
                description: loc.techCrdtDesc,
              ),
              _TechCard(
                icon: LucideIcons.shieldCheck,
                title: loc.techPbft,
                description: loc.techPbftDesc,
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildEcosystemSection(bool isMobile) {
    final loc = AppLocalizations.of(context)!;
    return _SectionContainer(
      isMobile: isMobile,
      backgroundColor: const Color(0xFF111827),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SizedBox(height: 16),
          _SectionTitle(text: loc.ecoTitle),
          const SizedBox(height: 24),
          _SectionBody(text: loc.ecoBody),
          const SizedBox(height: 32),
          _EcosystemFeature(
            title: loc.ecoAiBrowsers,
            description: loc.ecoAiBrowsersDesc,
            icon: LucideIcons.globe,
          ),
          _EcosystemFeature(
            title: loc.ecoSocial,
            description: loc.ecoSocialDesc,
            icon: LucideIcons.users,
          ),
          _EcosystemFeature(
            title: loc.ecoDb,
            description: loc.ecoDbDesc,
            icon: LucideIcons.database,
          ),
        ],
      ),
    );
  }

  Widget _buildFooter(bool isMobile) {
    final loc = AppLocalizations.of(context)!;
    return Container(
      width: double.infinity,
      padding: EdgeInsets.symmetric(
        horizontal: isMobile ? 24.0 : 64.0,
        vertical: 80.0,
      ),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [
            const Color(0xFF0A0A0A),
            const Color(0xFF0F172A),
          ],
        ),
      ),
      child: Column(
        children: [
          Text(loc.footerTitle,
            style: TextStyle(
              fontSize: isMobile ? 36 : 56,
              fontWeight: FontWeight.bold,
              color: Colors.white,
            ),
          ),
          const SizedBox(height: 24),
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 600),
            child: Text(loc.footerBody,
              textAlign: TextAlign.center,
              style: TextStyle(
                fontSize: 18,
                color: Colors.white70,
                height: 1.6,
              ),
            ),
          ),
          const SizedBox(height: 48),
          _HeroButton(
            text: loc.getStarted,
            isPrimary: true,
            onTap: () {
              // TODO: Get started link
            },
          ),
          const SizedBox(height: 64),
          Text(loc.copyright,
            style: TextStyle(color: Colors.white30, fontSize: 14),
          )
        ],
      ),
    );
  }
}

class _HeroButton extends StatefulWidget {
  final String text;
  final bool isPrimary;
  final VoidCallback onTap;

  const _HeroButton({
    required this.text,
    required this.isPrimary,
    required this.onTap,
  });

  @override
  State<_HeroButton> createState() => _HeroButtonState();
}

class _HeroButtonState extends State<_HeroButton> {
  bool _isHovered = false;

  @override
  Widget build(BuildContext context) {
    final loc = AppLocalizations.of(context)!;
    return MouseRegion(
      onEnter: (_) => setState(() => _isHovered = true),
      onExit: (_) => setState(() => _isHovered = false),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        transform: Matrix4.identity()..scale(_isHovered ? 1.05 : 1.0),
        child: ElevatedButton(
          onPressed: widget.onTap,
          style: ElevatedButton.styleFrom(
            backgroundColor: widget.isPrimary ? const Color(0xFF3B82F6) : Colors.white.withOpacity(0.05),
            foregroundColor: Colors.white,
            padding: const EdgeInsets.symmetric(horizontal: 32, vertical: 20),
            elevation: _isHovered ? 12 : 0,
            shadowColor: widget.isPrimary ? Colors.blueAccent.withOpacity(0.5) : Colors.transparent,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(12),
              side: widget.isPrimary ? BorderSide.none : BorderSide(color: Colors.white24),
            ),
          ),
          child: Text(
            widget.text,
            style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
          ),
        ),
      ),
    );
  }
}

class _SectionContainer extends StatelessWidget {
  final Widget child;
  final bool isMobile;
  final Color? backgroundColor;

  const _SectionContainer({
    super.key,
    required this.child,
    required this.isMobile,
    this.backgroundColor,
  });

  @override
  Widget build(BuildContext context) {
    final loc = AppLocalizations.of(context)!;
    return Container(
      width: double.infinity,
      color: backgroundColor ?? Colors.transparent,
      padding: EdgeInsets.symmetric(
        horizontal: isMobile ? 24.0 : 64.0,
        vertical: 80.0,
      ),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 1000),
          child: child,
        ),
      ),
    );
  }
}

class _SectionLabel extends StatelessWidget {
  final String text;
  const _SectionLabel({required this.text});

  @override
  Widget build(BuildContext context) {
    final loc = AppLocalizations.of(context)!;
    return Text(
      text.toUpperCase(),
      style: const TextStyle(
        color: Colors.blueAccent,
        fontWeight: FontWeight.bold,
        letterSpacing: 1.5,
        fontSize: 14,
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  final String text;
  const _SectionTitle({required this.text});

  @override
  Widget build(BuildContext context) {
    final loc = AppLocalizations.of(context)!;
    return Text(
      text,
      style: const TextStyle(
        color: Colors.white,
        fontWeight: FontWeight.w800,
        fontSize: 36,
        letterSpacing: -1,
        height: 1.2,
      ),
    );
  }
}

class _SectionBody extends StatelessWidget {
  final String text;
  const _SectionBody({required this.text});

  @override
  Widget build(BuildContext context) {
    final loc = AppLocalizations.of(context)!;
    return Text(
      text,
      style: const TextStyle(
        color: Colors.white70,
        fontSize: 18,
        height: 1.6,
      ),
    );
  }
}

class _TechCard extends StatefulWidget {
  final IconData icon;
  final String title;
  final String description;

  const _TechCard({
    required this.icon,
    required this.title,
    required this.description,
  });

  @override
  State<_TechCard> createState() => _TechCardState();
}

class _TechCardState extends State<_TechCard> {
  bool _isHovered = false;

  @override
  Widget build(BuildContext context) {
    final loc = AppLocalizations.of(context)!;
    return MouseRegion(
      onEnter: (_) => setState(() => _isHovered = true),
      onExit: (_) => setState(() => _isHovered = false),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 300),
        padding: const EdgeInsets.all(32),
        decoration: BoxDecoration(
          color: _isHovered ? Colors.white.withOpacity(0.05) : Colors.transparent,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(
            color: _isHovered ? Colors.blueAccent.withOpacity(0.5) : Colors.white10,
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(widget.icon, size: 32, color: Colors.blueAccent),
            const SizedBox(height: 24),
            Text(
              widget.title,
              style: const TextStyle(
                color: Colors.white,
                fontSize: 20,
                fontWeight: FontWeight.bold,
              ),
            ),
            const SizedBox(height: 12),
            Expanded(
              child: Text(
                widget.description,
                style: const TextStyle(color: Colors.white60, fontSize: 16, height: 1.5),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _EcosystemFeature extends StatelessWidget {
  final String title;
  final String description;
  final IconData icon;

  const _EcosystemFeature({
    required this.title,
    required this.description,
    required this.icon,
  });

  @override
  Widget build(BuildContext context) {
    final loc = AppLocalizations.of(context)!;
    return Padding(
      padding: const EdgeInsets.only(bottom: 24.0),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: Colors.blueAccent.withOpacity(0.1),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Icon(icon, color: Colors.blueAccent, size: 24),
          ),
          const SizedBox(width: 24),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 20,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  description,
                  style: const TextStyle(
                    color: Colors.white60,
                    fontSize: 16,
                    height: 1.5,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _QuickLinkCard extends StatefulWidget {
  final String title;
  final IconData icon;
  final Color color;
  final VoidCallback onTap;

  const _QuickLinkCard({
    required this.title,
    required this.icon,
    required this.color,
    required this.onTap,
  });

  @override
  State<_QuickLinkCard> createState() => _QuickLinkCardState();
}

class _QuickLinkCardState extends State<_QuickLinkCard> {
  bool _isHovered = false;

  @override
  Widget build(BuildContext context) {
    final loc = AppLocalizations.of(context)!;
    return MouseRegion(
      onEnter: (_) => setState(() => _isHovered = true),
      onExit: (_) => setState(() => _isHovered = false),
      child: GestureDetector(
        onTap: widget.onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 200),
          transform: Matrix4.identity()..scale(_isHovered ? 1.05 : 1.0),
          width: 250,
          padding: const EdgeInsets.all(24),
          decoration: BoxDecoration(
            color: const Color(0xFF1A1A1A),
            borderRadius: BorderRadius.circular(16),
            border: Border.all(
              color: _isHovered ? widget.color.withOpacity(0.5) : Colors.white10,
            ),
            boxShadow: _isHovered
                ? [
                    BoxShadow(
                      color: widget.color.withOpacity(0.2),
                      blurRadius: 20,
                      spreadRadius: 2,
                    )
                  ]
                : [],
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(widget.icon, size: 36, color: widget.color),
              const SizedBox(height: 16),
              Text(
                widget.title,
                textAlign: TextAlign.center,
                style: const TextStyle(
                  color: Colors.white,
                  fontWeight: FontWeight.bold,
                  fontSize: 16,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
