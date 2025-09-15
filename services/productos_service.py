import logging
from typing import Dict, Optional
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, Field, validator

from .sheets_service import sheets_service


logger = logging.getLogger(__name__)


class Producto(BaseModel):
    id: str = Field(..., min_length=1)
    nombre: str = Field(..., min_length=1)
    precio: Decimal
    descripcion: str = Field(default="")
    activo: bool = True

    @validator('precio', pre=True)
    def _parse_precio(cls, v):
        if isinstance(v, (int, float, Decimal)):
            return Decimal(str(v))
        s = str(v).strip().replace('.', '').replace(',', '.')
        try:
            return Decimal(s)
        except (InvalidOperation, ValueError):
            raise ValueError('precio inválido')

    @validator('activo', pre=True)
    def _parse_activo(cls, v):
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ['true', '1', 'si', 'sí', 'yes']


class ProductosService:
    def __init__(self):
        self._cache: Dict[str, Producto] = {}
        self.reload()

    def reload(self) -> int:
        """Carga precios desde Google Sheets a memoria. Devuelve cantidad de productos."""
        try:
            rows = sheets_service.get_pricing_table()
            items: Dict[str, Producto] = {}
            for row in rows:
                # Espera columnas: id, nombre, precio, descripcion, activo
                try:
                    p = Producto(
                        id=row.get('id', ''),
                        nombre=row.get('nombre', ''),
                        precio=row.get('precio', '0'),
                        descripcion=row.get('descripcion', ''),
                        activo=row.get('activo', 'true'),
                    )
                    if p.activo:
                        items[p.id] = p
                except Exception as e:
                    logger.error(f"Producto inválido en Sheets: {row} -> {e}")
            self._cache = items
            logger.info(f"Productos cargados: {len(self._cache)}")
            return len(self._cache)
        except Exception as e:
            logger.error(f"Error cargando productos desde Sheets: {str(e)}")
            self._cache = {}
            return 0

    def get_producto(self, producto_id: str) -> Optional[Producto]:
        return self._cache.get(producto_id)

    def listar_productos(self) -> Dict[str, Producto]:
        return dict(self._cache)


productos_service = ProductosService()


