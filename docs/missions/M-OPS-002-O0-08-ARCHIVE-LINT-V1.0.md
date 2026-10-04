# M-OPS-002 · O0-08 · Formato causal de un import en archive · V1.0

## Visión y solicitud original del humano

Julián pidió «ejecutar toda la mega misión», configurar y revisar «con criterio y cuidado» y «todas las pruebas y pulido hasta increíble», autónomo hasta develop. Para O0-08 explicó que las instrucciones comunes son globales y «la documentación que alimentamos con juicio está en Atlas». No hay GO posterior de producción. Este cambio permite verificar la limpieza documental; no declara aceptado el circuito autónomo del Fixer.

## Tramo y decisiones

El líder encargó aislar el fallo isort del CI37188978048, recuperar la versión exacta de pip del runner, comparar antes/después del borrado documental y preparar únicamente formato de imports si era necesario. Prohibió desactivar el gate, modificar el workflow o actualizar dependencias por conveniencia. También exigió AST idéntico, preservación de los demás blobs y ninguna prueba de modelos/DB/AWS/Gmail.

**Decisión de la IA:** reproducir con Python3.10.21 y todas las versiones exactas del job en un entorno temporal propio, sin modificar librerías de aplicación. Aplicar únicamente el resultado del formatter al bloque probado. El nuevo registro documental acompaña el único archivo de código modificado. El líder conserva integración y nuevo CI; no se despliega este archivo público congelado.

## Causa demostrada y regla exacta

CI rojo: head `e7c4c132831e030fc62a2873c384e1558f19d81c`, job Lint & Format Check111396967036. La línea completa de instalación demuestra pip26.2.1, isort9.0.2, Black26.5.1 y flake8 7.4.1. El workflow instala linters sin pin y ejecuta `isort --check-only --profile black --line-length 120 app/ tests/`; `pyproject.toml` declara profile black, line_length120 y known_first_party app.

En `app/services/section_html_service.py`, el import aliased `SUB_IMAGE_MODEL as _SIM` va seguido de un import de un solo nombre, `SUB_IMAGE_RETRY_DELAY_SECONDS`, entre paréntesis y con coma final. En isort9.0.2, `output.py` marca `processed_as_imports_this_iteration` después de emitir el alias, y eso evita la expansión por `split_on_trailing_comma` del grupo normal que le sigue. Como ese único nombre cabe dentro de 120 caracteres, lo escribe en una línea.

Tres controles usando la herramienta nativa y esa configuración confirmaron la regla: alias seguido del bloque cambia; bloque sin alias conserva sus tres líneas; alias seguido de la línea final ya formateada no cambia. No se ejecutaron los imports ni código de proveedores.

La base `55108eb88a204948bfe5c6d7458cacec64b807f2` y develop sólo difieren en eliminar `CLAUDE.md`; el blob de Python era idéntico. Se restauró temporalmente sólo ese documento en el worktree propio y se retiró después: el comando completo falló de la misma forma con y sin él, con stdout/stderr idénticos. La configuración nativa también es semánticamente idéntica. Sus tres campos frozenset aparecen en orden JSON aleatorio entre procesos; se conservaron ambas salidas originales y se compararon como conjuntos únicamente esos campos, sin alterar opciones ordenadas ni el comando.

## Solución y comprobaciones

Único cambio de código: colapsar ese import de tres líneas en una. No cambia nombres, alias, orden de imports, funciones, constantes ni lógica.

| Gate | Resultado |
|---|---|
| Python/versiones | Python3.10.21, pip26.2.1, isort9.0.2, Black26.5.1, flake8 7.4.1 y todas las dependencias del job fijadas sólo en el entorno de reproducción. |
| Antes con/sin documento | isort completo exit1 en ambos; mismo error y configuración efectiva. |
| Después isort completo | Exacto comando de CI sobre app/ y tests/: exit0. |
| Después Black completo | Exacto comando de CI sobre app/ y tests/: exit0. |
| Después flake8 fatal | Exacto select E9,F63,F7,F82 sobre app/: exit0, cero. |
| Después flake8 avisos | Exacto comando exit-zero de CI: exit0, 54 avisos; no se llaman cero incidencias. |
| AST | `ast.dump(..., include_attributes=False)` idéntico antes/después, sin normalizar ni reordenar nodos. SHA256 `94bf91e1142caa7bd7f861833f0ba370b1e138247b6c7b381e8dda9cd4ebdf83`. |
| Código original/final | SHA256 `1f62348d973cd8e45c0c3dd5faeea4defbf661317273d2cd6a661c31fd319f0b` → `ed9186e5c49806757194b0581a1e31494f73123cde46b3bbe144388bfd6835a4`. |
| Whitelist | Sólo este archivo Python y este documento nuevo. Los otros 223 blobs/modos/entradas de develop se conservan. CLAUDE.md permanece ausente. |

## Procedencia y límites

Recibos, originales, comandos, configuración, errores del harness y manifest en `M-FIXER-EJECUCION-20261003/fxdb_herramientas/o0-08-reglas-v1/lint-archive-v1/`. La base develop tiene225 entradas antes y224 después de quitar CLAUDE; master tiene208 después y es otro árbol. Se conservaron los gitlinks existentes; no se inicializaron ni se leyeron sus contenidos.

El CI verde histórico26459866572 es del26-may sobre55108, pero sus logs dan HTTP410. No conocemos su versión de isort y no atribuimos por inferencia el cambio de resultado a una actualización concreta de herramienta. Lo probado es el defecto de formato bajo la herramienta y configuración actuales, independiente del borrado documental.

Host local Darwin arm64; el runner real es Ubuntu x64. Comparten Python y versiones/configuración verificadas, pero no se presenta el check local como otro CI físico del runner. El CI rojo dejó flake8 y pruebas/cobertura skipped. Los cuatro gates locales de lint pasan; falta el nuevo CI completo tras integración, y no se han ejecutado pruebas de aplicación, modelos, requests, DB, AWS, despliegues ni producción.

No se desactivó ningún gate, no cambió workflow/pyproject/requirements, no se actualizó la aplicación y no se restauró el CLAUDE eliminado. No hay porcentaje de aceptación deducido de estos checks.
