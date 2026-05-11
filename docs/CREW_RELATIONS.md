# Crew-Beziehungen — Liberty City RP-Event

**Verwendungszweck:** Diese Matrix wird in die Tabelle `crew_relations` eingespielt und ist damit Teil des KI-Auftragsprompts ([backend/prompts.py](../backend/prompts.py) `build_user_prompt()` zieht alle Relationen einer Crew in jeden Auftragsentwurf). Sie ist **intern** — die Notes erscheinen nicht im öffentlichen Event-Briefing, geben aber Spielleitern und der KI klare Aufhänger für Cross-Crew-Bezüge.

**Konvention:** `crew_a_id` ist immer die kleinere ID (verhindert Duplikate). `relation_type ∈ {allied, rival, hostile, business, neutral}`.

**Crew-IDs (Kurzreferenz, gelesen aus DB):**

| ID | Crew | District |
|---:|---|---|
| 1 | AOD MC | Algonquin |
| 2 | The Harlem Vipers | Algonquin |
| 3 | Asiatische Yakuza (Nishiki-kai) | Algonquin |
| 4 | Italienische Mafia | Algonquin |
| 5 | LOST MC | Bohan |
| 6 | Bohan Sequidors | Bohan |
| 7 | Los Aztecas | Bohan |
| 8 | Blue Union | Bohan |
| 9 | Broker Crossline Kings | Broker |
| 10 | The Fireflys | Broker |
| 11 | Jamaikanische Yardis | Broker |
| 12 | Broker Avenue Lords | Broker |
| 13 | Russian Mafia | Broker |
| 14 | Little Bay Pirates | Colony Island |
| 15 | Independent Smugglers | Colony Island |
| 16 | Blackline Security | Colony Island |
| 17 | Money over Bitches | Dukes |
| 18 | Dukes Latin Kings | Dukes |
| 19 | Spanish Lords | Dukes |
| 20 | Eastline Wolves | Dukes |
| 21 | Midtown 49ers | Dukes |

---

## Beziehungs-Matrix (34 Einträge)

### Algonquin — interne Spannungen

| `a_id` | Crew A | `b_id` | Crew B | `relation_type` | `notes` |
|---:|---|---:|---|---|---|
| 3 | Asiatische Yakuza | 4 | Italienische Mafia | `business` | Geteilte Theaterstraße, Übereinkunft seit zwei Generationen — gegenseitiger Respekt zwischen Don Carbone und Oyabun Tanaka, aber keine Wärme. Die Linie zwischen ihren Geschäften wird in keinem Vertrag erwähnt und in keinem Vertrag verletzt. |
| 1 | AOD MC | 4 | Italienische Mafia | `rival` | Drei Säulen, eine Stadt — beide kontrollieren je 25 % Algonquins. Die Mafia toleriert den Charter, der Charter trotzt der Mafia. Ungeschriebene Linien, an die sich beide halten — bis es einer nicht mehr tut. |
| 2 | The Harlem Vipers | 4 | Italienische Mafia | `hostile` | Die Vipers brechen alte Hierarchien, die Mafia sieht das als persönlichen Affront. 15 % gegen 25 % — bisher kein Krieg, aber jeder Vorfall wird gezählt. |
| 2 | The Harlem Vipers | 3 | Asiatische Yakuza | `neutral` | Distanziert. Beide Crews vermeiden den Konflikt, weil keiner ihn braucht — die Yakuza hat ihre eigene parallele Welt, die Vipers haben ihre Blocks. Wenn sich die Welten kreuzen, ist es noch nicht entschieden, wie. |
| 1 | AOD MC | 2 | The Harlem Vipers | `rival` | Der MC sieht die Vipers als „die Neuen", die Vipers sehen den MC als „die Alten". Wer in den nächsten Jahren in Algonquin neu denkt, gewinnt das Verhältnis. |
| 1 | AOD MC | 3 | Asiatische Yakuza | `neutral` | Drei Säulen, drei Welten. AOD und Yakuza haben sich seit Jahren nicht persönlich begegnet — und genau das ist die Übereinkunft. Stille als Vertrag. |

### Bohan — bröckelnder Modus vivendi

| `a_id` | Crew A | `b_id` | Crew B | `relation_type` | `notes` |
|---:|---|---:|---|---|---|
| 6 | Bohan Sequidors | 7 | Los Aztecas | `rival` | Beide Latino, beide Block-orientiert, beide stolz. Die Übereinkunft, sich nicht in die Reviere des anderen zu drängen, ist brüchig — und älter als die meisten Mitglieder. |
| 5 | LOST MC | 6 | Bohan Sequidors | `hostile` | Die Sequidors sehen den MC als Eindringling auf ihren Brücken. Der MC sieht die Sequidors als das, was im Weg steht. |
| 5 | LOST MC | 7 | Los Aztecas | `rival` | Die Aztecas wollen Stille im Barrio, der MC bringt Lärm. Es gab Verletzungen, aber keine Beerdigungen — bisher. |
| 6 | Bohan Sequidors | 8 | Blue Union | `business` | Kalter Modus vivendi: die Union „patrouilliert", die Sequidors „verstehen". Geld wechselt nicht den Besitzer — Schweigen tut es. |
| 5 | LOST MC | 8 | Blue Union | `hostile` | Ex-Cops gegen Outlaw-MC, klassisch und tief. Jede Patrouille der Union an der Brücke endet mit Worten, manche mit mehr. |

### Broker — Tanz der Nacht

| `a_id` | Crew A | `b_id` | Crew B | `relation_type` | `notes` |
|---:|---|---:|---|---|---|
| 9 | Broker Crossline Kings | 12 | Broker Avenue Lords | `business` | Lords haben die Hauptstraßen, Kings haben die Querstraßen — geteilter Kuchen, kalt aber funktional. Wer die Linie überschreitet, zahlt einen Anteil. |
| 12 | Broker Avenue Lords | 13 | Russian Mafia | `business` | Die Bratva liefert über den Hafen, die Lords öffnen die Türen, hinter denen geliefert wird. Niemand spricht öffentlich darüber. |
| 9 | Broker Crossline Kings | 11 | Jamaikanische Yardis | `allied` | Alte Bekanntschaft aus Mercer's Gym — Selecta hat dort einmal trainiert, lange vor der Crew. Die Allianz ist nicht in Verträgen, sondern in Erinnerungen. |
| 11 | Jamaikanische Yardis | 13 | Russian Mafia | `rival` | Streit um Hafen-Anteile, kalt seit dem letzten Winter. Beide Crews wissen, dass es nur eine Sache braucht, um den Streit wieder warm zu machen. |
| 10 | The Fireflys | 12 | Broker Avenue Lords | `hostile` | Die Lords sehen die Fireflys als Bedrohung des Club-Geschäfts — illegale Locations, kein Türsteher, kein Anteil. Mehrere Razzien wurden zugeflüstert. |
| 10 | The Fireflys | 11 | Jamaikanische Yardis | `business` | Die Yardis liefern Sound, die Fireflys liefern Locations. Eine Kooperation aus Notwendigkeit, die zur Freundschaft werden könnte. |

### Colony Island — Wasser, das niemandem gehört

| `a_id` | Crew A | `b_id` | Crew B | `relation_type` | `notes` |
|---:|---|---:|---|---|---|
| 14 | Little Bay Pirates | 15 | Independent Smugglers | `hostile` | Die Pirates haben in den letzten zwei Jahren mehrfach Lieferungen der Independents geentert. Die Captains' Council schweigt darüber öffentlich — aber sie haben Erinnerungen. |
| 15 | Independent Smugglers | 16 | Blackline Security | `business` | Heimliche Lieferantenkette: Blackline „bemerkt" bestimmte Transporte nicht, im Gegenzug bekommt sie Zugang zu Frachtbriefen, die ihr offiziell verschlossen wären. |
| 14 | Little Bay Pirates | 16 | Blackline Security | `hostile` | Die Pirates sind das, was Blackline auf dem Papier „bekämpft". In der Realität ist es ein wechselseitiges Foto-Album aus Vorfällen, das niemand veröffentlicht. |

### Dukes — Familienfehden

| `a_id` | Crew A | `b_id` | Crew B | `relation_type` | `notes` |
|---:|---|---:|---|---|---|
| 18 | Dukes Latin Kings | 19 | Spanish Lords | `rival` | Zwei Generationen alte Schwebe. Beide Crews lateinamerikanisch, beide stolz, beide überzeugt, dass die andere ein Schatten ist. Der Frieden hält, weil ihn niemand bricht. |
| 18 | Dukes Latin Kings | 21 | Midtown 49ers | `business` | Die 49ers vermitteln, die Kings schützen die Vermittlung. Eine Provision, die man nicht laut ausspricht, aber die jeder kennt. |
| 17 | Money over Bitches | 18 | Dukes Latin Kings | `hostile` | Die Kings sehen die MOB als respektlos, die MOB sieht die Kings als überholt. Der Konflikt ist symbolisch — und damit gefährlicher als ein Geld-Konflikt. |
| 17 | Money over Bitches | 20 | Eastline Wolves | `rival` | MOB streamt laut, Wolves bewegen leise — eine Reibung der Stile mehr als der Reviere. Mehrere Vorfälle vor dem Restaurant *Tbilisi*, jedes Mal wird die Tür danach repariert. |
| 19 | Spanish Lords | 21 | Midtown 49ers | `business` | Die Lords lassen die 49ers durch ihre Reviere — gegen Provision. Eine kalte Übereinkunft, die funktioniert, weil keiner mehr will. |
| 17 | Money over Bitches | 19 | Spanish Lords | `hostile` | Don Rafa verachtet den MOB-Stil. J-Stack provoziert, weil er weiß, dass es wirkt. Bisher Worte, mehr nicht. |

### Inter-District — die Stadt ist kleiner, als sie aussieht

| `a_id` | Crew A | `b_id` | Crew B | `relation_type` | `notes` |
|---:|---|---:|---|---|---|
| 4 | Italienische Mafia | 13 | Russian Mafia | `rival` | Alter Streit um Hafen-Anteile in Broker, kalt seit dem letzten Winter. Don Carbone und Pakhan Volkov haben sich seit Jahren nicht persönlich gesehen — sie kommunizieren über Mittler, die zählen. |
| 4 | Italienische Mafia | 18 | Dukes Latin Kings | `business` | Alte Übereinkunft zwischen El Padre und Don Carbone aus den Stadtkriegen: Konzessionen gegen Stille. Funktioniert seit acht Jahren. |
| 1 | AOD MC | 5 | LOST MC | `hostile` | Bruder-Clubs, die nie mehr Brüder waren. Eine ungelöste Fehde, die so alt ist, dass die meisten Mitglieder den Auslöser nicht mehr kennen — aber den Hass weitergeben. |
| 13 | Russian Mafia | 15 | Independent Smugglers | `business` | Die Bratva ist einer der größten Kunden der Independents. Welcher Captain für sie arbeitet, ändert sich von Lieferung zu Lieferung — Absicht. |
| 4 | Italienische Mafia | 16 | Blackline Security | `business` | Verträge auf Briefpapier, die nicht aussehen wie das, was sie sind. Magnus Thorsen war einmal bei einer Beerdigung der Carbones — als „Sicherheitsberater". |
| 7 | Los Aztecas | 19 | Spanish Lords | `allied` | Kulturelle Brücke. Don Rafa und Cruz Alvarez kennen sich seit der Schule — die einzige offene Allianz der beiden Bohan- und Dukes-Latinos. Über diese Allianz haben die Spanish Lords Verstecke und Logistik-Punkte in Bohan. |
| 6 | Bohan Sequidors | 19 | Spanish Lords | `business` | Geografische Notwendigkeit: die Spanish Lords betreiben Verstecke in Sequidor-Reviere. Carmen Rivera duldet das gegen einen Anteil — kein Bündnis, eine kalte Übereinkunft mit klaren Linien. |
| 6 | Bohan Sequidors | 11 | Jamaikanische Yardis | `business` | Die Yardies haben in Süd-Bohan Verteilerzentren auf Sequidor-Territorium. Selecta und La Loba haben sich vor zwei Jahren persönlich verständigt: Yardies bleiben still, Sequidors lassen sie arbeiten, beide profitieren. |
| 7 | Los Aztecas | 11 | Jamaikanische Yardis | `business` | Bestehende kulturelle Schiene zwischen Aztecas und Yardies — über Süd-Bohan operativ verstärkt. Gemeinsame Lieferketten ohne offene Allianz. |
| 2 | The Harlem Vipers | 17 | Money over Bitches | `business` | Junge Crews, ähnliches Mindset. Gelegentliche Kooperationen, immer informell, nie schriftlich. Cobra und J-Stack telefonieren — selten, aber direkt. |
| 10 | The Fireflys | 17 | Money over Bitches | `allied` | Beide jung, beide laut, beide Internet-orientiert. Die einzige offene Allianz quer durch die Halbinseln. Phantom postet Forty's Tracks. |
| 5 | LOST MC | 14 | Little Bay Pirates | `business` | Die Pirates liefern via Wasser, der LOST verteilt via Land. Eine Logistik-Kette, die Wreck und Hook auf einer Bierdose besiegelt haben. |
| 13 | Russian Mafia | 20 | Eastline Wolves | `neutral` | Zwei osteuropäische Mächte, eine Stadt — die Bratva (Broker, 40 % dort) und die Wolves (Dukes, 35 % dort) treffen sich nie persönlich. Genau das ist die Übereinkunft. Beide wissen, dass eine osteuropäische Front in Liberty City keiner von ihnen leisten könnte. (Keine Verwandtschaft zwischen den beiden Volkov — eine Frage, die schon mal blutig endete.) |
| 4 | Italienische Mafia | 20 | Eastline Wolves | `rival` | Carbones haben über die Latin-Kings-Brücke einen Außenposten in Dukes (20 % Stadtteilmacht). Die Wolves (35 %) sehen das als geduldete Anwesenheit, nicht als Recht. Die Linie hält — unter Spannung. |
| 4 | Italienische Mafia | 21 | Midtown 49ers | `business` | Die 49ers sind die einzige Crew der Stadt, die für jede der drei Algonquin-Säulen (Mafia, Yakuza, AOD) gleichzeitig arbeiten kann, ohne Interessenkonflikte zu erzeugen. Carbone nutzt das. |

---

## Asymmetrie-Hinweise (für Spielleiter)

- **Vernetzteste Crews** (>5 Beziehungen): Italienische Mafia (8), Russian Mafia, Latin Kings, MOB, Eastline Wolves, Bohan Sequidors (7), Los Aztecas. Diese Crews sind „Knotenpunkte" — Aufträge, die sie betreffen, ziehen leicht andere Crews mit. Bohan ist insgesamt der dichteste Beziehungs-Knoten der Stadt — die 45-%-Latino-Achse und die Außenposten anderer Stadtteile machen Bohan zur Bühne, auf der die meisten Eskalationen sich verflechten.
- **Isolierte Crews** (≤3 Beziehungen): Asiatische Yakuza / Nishiki-kai (3 — bewusst zurückhaltend, parallele Welt), Blackline Security (2). Diese Crews sind dramaturgisch *Reserven* — wenn sie sich bewegen, bedeutet es etwas.
- **Brüchige Übereinkünfte** (`business` zwischen Crews mit Geschichte): Sequidors↔Blue Union, Avenue Lords↔Russian Mafia, Independents↔Blackline, Mafia↔49ers. Erste Kandidaten für Eskalation im Eventverlauf.
- **Allianzen** (`allied`, selten): Crossline Kings↔Yardis, Aztecas↔Spanish Lords, Fireflys↔MOB. Die einzigen drei echten Bündnisse — sie schaffen die Möglichkeit für *Blöcke*, falls das Event eskaliert.
- **Osteuropäische Achse**: Bratva (Broker 40 %) ↔ Wolves (Dukes 35 %) ist `neutral` — eine kalte Übereinkunft. Wenn diese Linie kippt, kippt halb Liberty City.

## Hinweis: Außenposten ohne eigene Crew-IDs

Mehrere Stadtteile haben Außenposten von Crews mit Stammsitz andernorts. Diese laufen operativ unter der Stamm-Crew, aber sie schaffen Stadtteil-Präsenz, die in Aufträgen relevant werden kann:

- **Italienische Mafia** (Stammsitz Algonquin, ID 4) hat Außenposten in **Broker** (10 % Stadtteilmacht) und **Dukes** (20 %).
- **Petrovsky Bratva** (Stammsitz Broker, ID 13) hat einen Außenposten auf **Colony Island** (10 %).
- **Jamaikanische Yardis** (Stammsitz Broker, ID 11) haben in **Bohan** Verteilerzentren (Teil des 45-%-Latino-Blocks).
- **Spanish Lords** (Stammsitz Dukes, ID 19) haben in **Bohan** Verstecke und Logistik-Punkte (Teil des 45-%-Latino-Blocks).
- **Carbones, Bratva, Yakuza, Avenue Lords, Wolves** haben alle in **Bohan** mindestens ein Versteck oder Operativ-Punkt — Bohan ist die unsichtbare Werkstatt der ganzen Stadt, ohne dass diese Crews Stadtteilmacht beanspruchen.

In KI-Aufträgen für die Stamm-Crew kann diese Außenposten-Präsenz organisch erwähnt werden, ohne dass eine separate Crew nötig wäre.

## Offen für Erweiterung

Ungenutzte Verbindungen, die später nachgepflegt werden können, falls die Story sie braucht:

- AOD MC ↔ Bratva (zwei alte Schulen, könnten sich respektieren oder kollidieren)
- Asiatische Yakuza / Nishiki-kai ↔ Aztecas (Disziplin-Crews mit Berührungspunkten in Stille und Codex)
- Eastline Wolves ↔ Fireflys (junge Subkultur-Linien, könnten kooperieren oder rivalisieren)
- Latin Kings ↔ Aztecas (Latino-Block, derzeit `neutral` — heizbar)
- Eastline Wolves ↔ Latin Kings (Stadtteil-Nachbarn ohne aktive Beziehung — aktivierbar bei Wolves/Mafia-Eskalation)

Diese werden im Initial-Seed *bewusst* ausgelassen, damit sie als organischer Story-Hebel verfügbar bleiben.
