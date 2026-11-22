// Render every icon from public/logo.svg: web (PWA, favicon) and Android (legacy launcher, adaptive layer, splash).
//   node web/scripts/icons.mjs
import { Resvg } from "@resvg/resvg-js"
import { mkdirSync, readFileSync, writeFileSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

const web = join(dirname(fileURLToPath(import.meta.url)), "..")
const res = join(web, "..", "android", "app", "src", "main", "res")
const logo = readFileSync(join(web, "public", "logo.svg"), "utf8")
const mark = logo.slice(logo.indexOf("<path"), logo.lastIndexOf("</svg>"))
const defs = logo.slice(logo.indexOf("<defs>"), logo.indexOf("</defs>") + 7)

function png(svg, size, out) {
  mkdirSync(dirname(out), { recursive: true })
  writeFileSync(out, new Resvg(svg, { fitTo: { mode: "width", value: size } }).render().asPng())
}

// the mark scaled around the centre: 1 = as drawn on the square
const scaled = (k) => `<g transform="translate(256 256) scale(${k}) translate(-256 -256)">${mark}</g>`
const svg = (body) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">${defs}${body}</svg>`

const square = logo
// legacy launcher: a circle, corners transparent (Android lint IconLauncherShape)
const round = svg(`<circle cx="256" cy="256" r="256" fill="url(#bg)"/>${scaled(0.86)}`)
// adaptive icon: full bleed, the mark inside the 66% safe zone
const adaptive = svg(`<rect width="512" height="512" fill="url(#bg)"/>${scaled(0.66)}`)
// splash: the square logo at half size, centred on a transparent canvas
const body = logo.slice(logo.indexOf("<rect"), logo.lastIndexOf("</svg>"))
const splash = svg(`<g transform="translate(128 128) scale(.5)">${body}</g>`)

png(square, 192, join(web, "public", "icon-192.png"))
png(square, 512, join(web, "public", "icon-512.png"))
png(adaptive, 512, join(web, "public", "icon-maskable-512.png"))
for (const [d, k] of [["mdpi", 1], ["hdpi", 1.5], ["xhdpi", 2], ["xxhdpi", 3], ["xxxhdpi", 4]]) {
  png(round, Math.round(48 * k), join(res, `mipmap-${d}`, "ic_launcher.png"))
  png(adaptive, Math.round(108 * k), join(res, `mipmap-${d}`, "ic_maskable.png"))
  png(splash, Math.round(300 * k), join(res, `drawable-${d}`, "splash.png"))
}
