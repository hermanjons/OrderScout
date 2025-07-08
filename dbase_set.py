from sqlmodel import SQLModel
from Core.utils.model_utils import get_engine

from models.stocks import StockData, MatchData

SQLModel.metadata.create_all(engine)  # tüm tablo sınıfları aynı metadata'ya kayıtlıysa yeterlidir







