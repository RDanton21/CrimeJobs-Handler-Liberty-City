# SEKT6R Crime Automation — System-Überblick

Ein KI-gestütztes Verwaltungssystem für ein GTA-Liberty-City-Roleplay. Es
erzeugt Aufträge, koordiniert das Personal dahinter und pflegt die Beziehungen
zwischen den Gruppierungen der Stadt — alles über ein Web-Dashboard und den
Discord-Bot „Il Padrino".

Das System besteht aus drei zusammenspielenden Säulen.

---

## Säule 1 — Auftrags-Automation

Der Kern: KI-generierte, atmosphärische Aufträge für jede Gruppierung.

- Aufträge werden per KI im Stil eines Mafia-Bosses erzeugt — kryptisch,
  literarisch, auf die jeweilige Gruppierung zugeschnitten.
- Jede Gruppierung hat eine Hintergrund-Story, ein kriminelles Geschäft und
  Beziehungen zu anderen — die KI zieht all das in jeden Auftrag ein.
- Aufträge lassen sich vor dem Versand ansehen, bearbeiten und mit Bild
  versehen. Erst ein zweiter Klick schickt sie an Discord.
- Wahlweise vollständig KI-generiert, KI-umgeschrieben aus eigenem Rohtext,
  oder reiner Klartext.
- Massen-Auftrag an alle oder an einen ganzen Stadtteil auf einmal.
- Zeitgesteuerter Versand und ein Countdown bis zur Frist.
- KI-Vorschläge für Folgeaufträge, basierend auf der letzten Reaktion.

## Säule 2 — Personal-Börse

Die Bühne hinter dem Auftrag: welche Rollen es braucht und wer sie besetzt.

- Zu jedem Auftrag erzeugt die KI einen Personalbedarf — welche NPCs, Rollen,
  Kostüme und Einsatzorte gebraucht werden.
- Der Bedarf wird auf einer eigenen öffentlichen Seite ausgespielt, auf der sich
  Spieler für Rollen eintragen können.
- Der Personalbedarf kann schon vor dem Auftrag sichtbar sein — der eigentliche
  Auftragstext bleibt dabei verborgen, bis er offiziell rausgeht.
- Warteliste mit automatischem Nachrücken, Anwesenheits-Erfassung und
  Erinnerungen per Direktnachricht vor dem Einsatz.
- Rollen werden während der Session überwacht; eine eigene Bilanz zeigt jedem
  Spieler seine Einsätze.

## Säule 3 — Beziehungs-Management

Wer steht zu wem wie — und warum.

- Jede Gruppierung meldet über eine Discord-Umfrage per Auswahlmenü, wie sie zu
  den anderen steht.
- Eine Auswertung stellt beide Sichten gegenüber und markiert, wo sie sich
  widersprechen.
- Widersprüche löst wahlweise die Spielleitung von Hand oder ein KI-Schiedsspruch
  auf, der die Storys beider Seiten liest und begründet entscheidet.
- Der finale Stand wird bewusst freigegeben und steuert ab da die
  Auftragsgenerierung — samt der Begründung, warum zwei Gruppen so zueinander
  stehen.

---

## Discord-Integration

- Eigener Bot, der Aufträge, Umfragen und Ankündigungen in die passenden
  Channels postet.
- Reaktionen der Bosse (erledigt / fehlgeschlagen / nicht durchführbar) werden
  direkt am Auftrag erfasst.
- Interaktive Auswahlmenüs für die Beziehungs-Erhebung, die auch einen
  Bot-Neustart überstehen.
- Dynamische Zeitstempel und Countdowns, die jedem Leser seine eigene Zeitzone
  anzeigen.

## Verwaltung & Dashboard

- Zentrales Web-Dashboard mit Live-Statistik über alle Reaktionen.
- Gang-Verwaltung mit KI-Assistent zum Anlegen neuer Gruppierungen samt Story
  und Beziehungen.
- Ranking der Gruppierungen nach Performance, inklusive manueller Bonus-Punkte.
- Story-Editor, Archiv und Export.
- Gruppierungen lassen sich auf inaktiv setzen — sie verschwinden dann aus
  Massenversand, Ranking und Statistik, ohne gelöscht zu werden.
- Eine separate Kommandozentrale überwacht und steuert alle Dienste des Systems.

---

## Technik in Kürze

- Web-Backend und Discord-Bot als getrennte Dienste, die über eine interne
  Schnittstelle zusammenarbeiten.
- Anbindung an führende KI-Anbieter, mit auswählbaren Modellen und anpassbaren
  System-Prompts.
- Vollständig containerisiert, hinter einem Reverse-Proxy mit automatischen
  HTTPS-Zertifikaten.
- Läuft eigenständig auf einem eigenen Server.
