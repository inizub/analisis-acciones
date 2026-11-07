# 0010. Instalación desde GitHub con alcance de usuario

**Estado:** aplicada. **Fecha:** 6-7-nov-2026.

## Contexto
El usuario esperaba que el plugin "viviera en su cuenta" y estuviera disponible en cualquier equipo y carpeta. Un plugin de
Claude Code **no se guarda en la cuenta**, sino en cada ordenador (`~/.claude`); necesita además `uv`, `bash` y Python para
sus scripts, así que tampoco puede ser un skill suelto en claude.ai.

## Decisión
- Instalación con **alcance `user`** (cualquier carpeta del PC), desde el marketplace de GitHub `inizub/analisis-acciones`
  (el repo es público desde el 7-nov). En otro PC: `claude plugin marketplace add inizub/analisis-acciones` y
  `claude plugin install analisis-acciones@analisis-acciones --scope user`.
- Para ver cambios: `git push`, `claude plugin marketplace update analisis-acciones` y `claude plugin update ...`
  (requiere subir la versión). Hay que abrir una sesión nueva.
- `journal_dir` se guarda en `~/.claude/settings.json` (`pluginConfigs`) y **se borra al desinstalar**: hay que restaurarlo.
- El marketplace local (carpeta del repo) que se usó al desarrollar se sustituyó por el de GitHub: el nombre del marketplace
  es único y una entrada en `extraKnownMarketplaces` con otra fuente impedía añadir el de GitHub.
- Los correos de los commits usan `290834249+inizub@users.noreply.github.com` porque GitHub rechaza el correo personal.

## Alternativas descartadas
- **Instalación local por carpeta:** los cambios se veían al instante, pero solo en este PC y en un proyecto.
- **Skill suelto en la cuenta de claude.ai:** no puede ejecutar los scripts ni leer/escribir el diario.

## Consecuencias
- Cada cambio exige subir versión para propagarse; es un paso más, pero el repositorio es la fuente única.
- El diario (`journal/`) no viaja con el plugin: se ignora en git para no publicar predicciones personales.

## Dónde está
`.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `README.md`, `~/.claude/settings.json` (fuera del repo).
