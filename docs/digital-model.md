# Цифровая модель городской среды (2-й семестр, защита 14.05.2026)

Источник: `presentations/2026-05-14_digital_model_primorsk.pdf`. Курс «Цифровое моделирование урбанизированных
территорий» (Т. Чурякова). Состав на защите: Яковлев, Ренгач, Комарова, Непомнящая, Яцуба, Саркисова. Сейчас в команде также Цыганов Виктор.

## Карты презентации → слои репозитория

| Слайд | Карта | Слои `data/processed/` |
|---|---|---|
| 3 | Общие сведения, положение в ЛО и агломерации | `boundary` |
| 4 | Функциональное зонирование | `landuse` (ГП, 25 типов зон) |
| 5 | Природные объекты и ООПТ | `forest`, `water`, `bay`, `lake`, `river`, `services/oopt` |
| 6 | Здания: жилые и нежилые | `building.is_living` |
| 7 | Здания: этажность | `building.number_of_floors` |
| 8 | Транспортная инфраструктура | `roads`, `railways`, `services/bus_stop, train_station, parking, fuel, port, airport` |
| 9–11 | Социальная инфраструктура | `services/school, kindergarten, extra_education, polyclinic, hospital, pharmacy, dentist, emergency, library, museum, community_centre, religion, pitch, playground, park` |
| 12 | Инженерная инфраструктура | `services/boilerhouse, pumping_station, wastewater_plant, cell_tower` |
| 13 | Административная инфраструктура | `services/mfz, police, post_office, fire_station` |
| 14–15 | Коммерческая инфраструктура | `services/supermarket, convenience, cafe, restaurant, hotel, bank, beauty, hairdresser, clothes, outpost` |
| 16 | Объекты отдыха | `services/camp, public_bath, historic` |
| 17 | Объекты специального назначения | `services/cemetery, agricultural_services` |
| 18 | Кварталы | `blocks` |

## Оценка

Предварительный итог по курсу — **85 баллов (4B)**. Итоговое замечание: «не выполнена корректировка домов
жилой/нежилой, реки в разных типах геометрии». Исправления после защиты — `docs/review_comments.md`.

Важно: карты 6–7 в защищённой презентации построены по старой версии `building` (жилыми отмечены только дома из
реестра, 1 516). После исправлений жилых домов 3 876 — при повторном использовании карт их нужно перестроить.
