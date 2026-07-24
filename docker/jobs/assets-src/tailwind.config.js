/** Tailwind-Build-Config der Personal-Boerse.
 *  Content-Scan ueber das ausgelieferte HTML + die ausgelagerte Alpine-Komponente,
 *  damit alle (auch in :class-Strings gebauten) Klassen im CSS landen.
 *  Pfade relativ zu diesem Verzeichnis (docker/jobs/assets-src/).
 */
module.exports = {
  content: [
    "../src/static/index.html",
    "../src/static/app.js",
  ],
  theme: { extend: {} },
}
