from aiogram.types import Message
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from states.states import ProductInfo
from database.models import Product
from sqlalchemy.ext.asyncio import AsyncSession

router = Router()


# @router.message(
#     F.text.lower() == "получить информацию по товару")
# async def get_article_product(message: Message, state: FSMContext):
#     await message.reply("Хорошо, введите артикул товара")
#     await state.set_state(ProductInfo.get_article)
#
#
# @router.message(ProductInfo.get_article)
# async def get_info_product(message: Message, state: FSMContext, session: AsyncSession):
#     # await state.update_data(chosen_food=message.text.lower()) \ get_data()
#     try:
#         article = int(message.text)
#     except ValueError:
#         await message.answer("Введите корректный артикул!")
#         return
#     name = "test name"
#     price = 123.123
#     rating = 123
#     count = 123
#     new_product = Product(
#         name=name,
#         article=article,
#         price=price,
#         rating=rating,
#         count=count
#     )
#     session.add(new_product)
#     await session.commit()
#     await message.answer(f"Вот информация по товару с артикулом {article}: нет инфы!")
#     await state.set_state(None)
#
#
# @router.message(F.text.lower() == "остановить уведомления")
# async def stopping_notifications(message: Message):
#     await message.reply("Получение уведомлений прекращено!")
#
#
# @router.message(F.text.lower() == "получить информацию из бд")
# async def get_products(message: Message):
#     await message.reply("Момент, запрашиваю инфу...")
