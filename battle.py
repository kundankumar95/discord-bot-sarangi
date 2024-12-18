import discord
from discord.ext import commands
import random
import json
import asyncio
import os
from dotenv import load_dotenv
from datetime import datetime
from prettytable import PrettyTable
from pymongo import MongoClient
from flask import Flask
import threading
import asyncio

load_dotenv()


port = os.getenv('PORT', 5000) 
app = Flask(__name__)
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)


MONGO_URI = os.getenv("MONGO_URI")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
client = MongoClient(MONGO_URI)
db = client["beingSarangi"] 
users_collection = db.users  
available_cards_collection = db.available_cards

collections = db.list_collection_names()
print(f"Collections in database: {collections}")

active_battles = []

async def send_card_images(user, selected_cards):
    """Send each card as a separate embed."""
    for card in selected_cards:
        embed = discord.Embed(
            title=f"{card.get('name')}",
            description=f"Rating: {card.get('rating')}",
            color=discord.Color.blue()
        )
        image_url = card.get('image_url')
        if image_url:
            embed.set_image(url=image_url)
        await user.send(embed=embed)

async def send_card(user, card_name):
    """Retrieve and send card information from MongoDB."""
    user_data = users_collection.find_one({"user_id": str(user.id)}) 

    if not user_data:
        await user.send("Sorry, user data not found.")
        return

    found_card = None
    for card in user_data.get("cards", []): 
        if card["name"].lower() == card_name.lower():
            found_card = card
            break

    if not found_card:
        await user.send(f"Sorry, I couldn't find any information for the card '{card_name}'.")
        return

    embed = discord.Embed(
        title=found_card["name"],
        description=(
            f"Rating: {found_card['rating']}\n"
            f"Price: {found_card['price']}\n"
            f"AGR: {found_card['agr']}\n"
            f"Apps: {found_card.get('APPS', 'N/A')}"
        ),
        color=discord.Color.blue()
    )

    image_url = found_card.get("image_url")
    if image_url:
        embed.set_image(url=image_url)

    await user.send(embed=embed)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')

@bot.command(name="roll")
async def give_daily_cards(ctx):
    user_id = str(ctx.author.id)
    today = datetime.now().date().strftime("%Y-%m-%d")

    user_profile = users_collection.find_one({"user_id": user_id})

    if not user_profile:
        user_profile = {
            "user_id": user_id,
            "name": ctx.author.name,
            "date": "", 
            "points": 0, 
            "wins": 0,    
            "losses": 0, 
            "cards": [],
            "visit_count": 0
        }
        users_collection.insert_one(user_profile)

    available_cards = list(available_cards_collection.find({}))
    if not available_cards:
        await ctx.author.send("No cards are available at the moment. Please try again later.")
        return

    if user_profile.get("date") != today:
        user_profile["visit_count"] = 0
        user_profile["date"] = today
        users_collection.update_one({"user_id": user_id}, {"$set": {"date": today, "visit_count": 0}})

    if user_profile.get("visit_count") == 0:
        daily_card = random.choice(available_cards)
        user_profile["cards"] = [daily_card]
        user_profile["visit_count"] += 1

        available_cards_collection.delete_one({"_id": daily_card["_id"]})

        users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"cards": user_profile["cards"], "visit_count": user_profile["visit_count"]}}
        )
        await ctx.author.send(f"Here is your first card for today:\n{daily_card['image_url']}")
    elif user_profile.get("visit_count") == 1:
        daily_card = random.choice(available_cards)
        user_profile["cards"].append(daily_card)
        user_profile["visit_count"] += 1

        available_cards_collection.delete_one({"_id": daily_card["_id"]})

        users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"cards": user_profile["cards"], "visit_count": user_profile["visit_count"]}}
        )
        await ctx.author.send(f"Here is your second card for today:\n{daily_card['image_url']}")
    else:
        await ctx.send(f"{ctx.author.mention}, you’ve already received your cards today. Check this link for more info: https://www.BeingSarangi.com")



def save_user_data(user_data):
    try:
        for user_id, user_profile in user_data["users"].items():
            users_collection.update_one(
                {"user_id": user_id}, 
                {"$set": user_profile}, 
                upsert=True  
            )
        print("User data saved successfully.")
    except Exception as e:
        print(f"Error saving user data to MongoDB: {e}")

@bot.command()
async def battle(ctx: commands.Context, opponent: str):
    try:
        opponent_user = await commands.UserConverter().convert(ctx, opponent)

        userA_id = str(ctx.author.id)
        userB_id = str(opponent_user.id)

        userA_data = users_collection.find_one({"user_id": userA_id})
        userB_data = users_collection.find_one({"user_id": userB_id})

        if not userA_data or not userB_data:
            await ctx.send("One or both players don't exist in the system.")
            return

        userA_cards = userA_data.get("cards", [])
        userB_cards = userB_data.get("cards", [])

        if len(userA_cards) < 3 or len(userB_cards) < 3:
            await ctx.send("One of the players doesn't have enough cards to battle! Both players need at least 3 cards.")
            return

        bot_selected_A = random.sample(userA_cards, 3)
        bot_selected_B = random.sample(userB_cards, 3)

        battle_data = {
            "userA_id": userA_id,
            "userB_id": userB_id,
            "userA_cards": bot_selected_A,
            "userB_cards": bot_selected_B,
            "status": "pending"
        }
        active_battles[userA_id] = battle_data
        active_battles[userB_id] = battle_data

        await ctx.send(f"{ctx.author.mention} challenged {opponent_user.mention} to a battle! Type `!accept` to join.")

        await send_card_images(ctx.author, bot_selected_A)
        await send_card_images(opponent_user, bot_selected_B)

    except commands.CommandError as e:
        await ctx.send(f"An error occurred: {e}")
        print(f"Error in battle command: {e}")
    except Exception as e:
        await ctx.send(f"An unexpected error occurred: {e}")
        print(f"Unexpected error in battle command: {e}")


@bot.command()
async def accept(ctx):
    """Accept a pending battle and allow both players to select additional cards."""
    user_id = ctx.author.id
    battle_data = next((battle for battle in active_battles.values() 
                        if battle.get('userB_id') == user_id and battle.get('status') == 'pending'), None)

    if not battle_data:
        await ctx.send("No pending battle found for you to accept.")
        return

    userA = bot.get_user(battle_data['userA_id'])
    userB = ctx.author
    await ctx.send(f"{userA.mention} and {userB.mention} are ready for battle! Let’s begin!")
    
    await send_card_images(userA, battle_data['userA_cards'])
    await send_card_images(userB, battle_data['userB_cards'])

    await ctx.send("Both players, select two additional cards to complete your hand.")

    try:
        await get_additional_cards(ctx, battle_data, userA, userB)
        del active_battles[battle_data['userA_id']]
        del active_battles[battle_data['userB_id']]
    except asyncio.TimeoutError:
        await ctx.send("A player took too long to select their cards. The battle has been canceled.")
        del active_battles[battle_data['userA_id']]
        del active_battles[battle_data['userB_id']]



async def get_additional_cards(ctx, battle):
    """Prompt both players to select two additional cards."""
    userA_id = battle['userA_id']
    userB_id = battle['userB_id']

    userA_initial_cards = battle['userA_cards']
    userB_initial_cards = battle['userB_cards']

    userA = bot.get_user(userA_id)
    userB = bot.get_user(userB_id)

    try:
        userA_hand = await prompt_user_for_cards(userA, userA_initial_cards)
        userB_hand = await prompt_user_for_cards(userB, userB_initial_cards)

        full_userA_hand = userA_initial_cards + userA_hand
        full_userB_hand = userB_initial_cards + userB_hand

        await ctx.send("Both players have selected their cards. Let the battle begin!")
        await start_battle(ctx, battle, full_userA_hand, full_userB_hand)

    except asyncio.TimeoutError:
        await ctx.send("A player took too long to select their cards. The battle has been canceled.")

async def prompt_user_for_cards(user, available_cards):
    """Prompt a user to select two additional cards."""
    def check(m):
        return m.author.id == user.id and m.channel.type == discord.ChannelType.private

    selected_cards = []
    available_card_names = [card['name'] for card in available_cards]

    try:
        await user.send(f"Select two additional cards from the following: {', '.join(available_card_names)}")

        for _ in range(2):
            await user.send("Type the name of the card you want to select:")
            msg = await bot.wait_for('message', check=check, timeout=60.0)
            card_name = msg.content.strip()

            if card_name in available_card_names and card_name not in selected_cards:
                selected_cards.append(card_name)
                await send_card(user, card_name)
            else:
                await user.send("Invalid or duplicate card selected. Please try again.")
                continue

        return [get_card_by_name(name, available_cards) for name in selected_cards]

    except asyncio.TimeoutError:
        await user.send("You took too long to select your cards.")
        raise

def get_card_by_name(card_name, cards):
    """Retrieve a card object by its name."""
    return next((card for card in cards if card['name'].lower() == card_name.lower()), None)

async def start_battle(ctx, battle, userA_initial_cards, userB_initial_cards, card_name1, card_name2, card_name1_b, card_name2_b):
    """Begin the battle after players select their cards."""
    await ctx.send("Both players have selected their cards. Let the battle begin!")

    def map_card_names_to_objects(card_names, available_cards):
        selected_cards = []
        for name in card_names:
            card = next((c for c in available_cards if c['name'].lower() == name.lower()), None)
            if card:
                selected_cards.append(card)
        return selected_cards

    userA_hand = userA_initial_cards + map_card_names_to_objects([card_name1, card_name2], userA_initial_cards)
    userB_hand = userB_initial_cards + map_card_names_to_objects([card_name1_b, card_name2_b], userB_initial_cards)

    if len(userA_hand) != len(userA_initial_cards) + 2 or len(userB_hand) != len(userB_initial_cards) + 2:
        await ctx.send("Error mapping card names to card objects. Please try again.")
        return

    print(f"User A Hand: {userA_hand}")
    print(f"User B Hand: {userB_hand}")

    await start_battle_rounds(ctx, userA_hand, userB_hand, battle)


async def start_battle_rounds(ctx, userA_hand, userB_hand, battle):
    """Conducts the battle rounds between two users."""
    userA = bot.get_user(battle['userA_id'])
    userB = bot.get_user(battle['userB_id'])
    
    valid_stats = ['rating', 'apps', 'agr', 'sv', 'g/a', 'tw']

    for round_num in range(1, 6):
        await ctx.send(f"Round {round_num} begins!")

        cards_message_a = "\n".join([f"{card['name']} - {card['rating']} rating, {card['APPS']} apps, {card['agr']} agr, {card.get('SV', 'N/A')} SV, {card.get('G/A', 'N/A')} G/A, {card.get('TW', 'N/A')} TW" for card in userA_hand if card is not None])
        cards_message_b = "\n".join([f"{card['name']} - {card['rating']} rating, {card['APPS']} apps, {card['agr']} agr, {card.get('SV', 'N/A')} SV, {card.get('G/A', 'N/A')} G/A, {card.get('TW', 'N/A')} TW" for card in userB_hand if card is not None])

        await userA.send(f"Choose a card and a stat (Rating, APPS, AGR, SV, G/A, TW):\n{cards_message_a}")
        await userB.send(f"Choose a card (same stat will be used for comparison for User B):\n{cards_message_b}")

        def check_a(m):
            if m.author.id == userA.id:
                parts = m.content.split()
                if len(parts) >= 2:  
                    stat_name = parts[-1].lower()
                    card_name = ' '.join(parts[:-1]).lower() 
                    if any(card['name'].lower() == card_name for card in userA_hand) and stat_name in valid_stats:
                        return True
                    else:
                        m.channel.send("Invalid input! Please enter the card name followed by the stat (e.g., 'Alexander Isak rating').")
            return False

        def check_b(m):
            if m.author.id == userB.id:
                card_name = m.content.strip().lower()
                if any(card['name'].lower() == card_name for card in userB_hand):
                    return True
                else:
                    m.channel.send("Invalid input! Please enter the card name (e.g., 'Bruno Guimaraes').")
            return False

        try:
            message_a = await bot.wait_for('message', check=check_a, timeout=200.0)
            message_a_content = message_a.content.strip().split()
            if len(message_a_content) == 2:
                card_a, stat_a = message_a_content
            elif len(message_a_content) == 3:
                card_a = f"{message_a_content[0]} {message_a_content[1]}" 
                stat_a = message_a_content[2]
            else:
                await ctx.send("Invalid input. Please enter either two or three words.")
                return

            selected_card_a = next(card for card in userA_hand if card['name'].lower() == card_a.lower())
            await send_card_images(userB, [selected_card_a])

            message_b = await bot.wait_for('message', check=check_b, timeout=200.0)
            card_b = message_b.content.strip().lower()
            selected_card_b = next(card for card in userB_hand if card['name'].lower() == card_b)

            await send_card_images(userA, [selected_card_b])
            stat_value_a = selected_card_a.get(stat_a, "N/A")
            stat_value_b = selected_card_b.get(stat_a, "N/A")
            
            if stat_value_a == "N/A":
                stat_value_a = 0
            if stat_value_b == "N/A":
                stat_value_b = 0

            userA_score = 0
            userB_score = 0
            if stat_value_a > stat_value_b:
                round_winner = "User A"
                userA_score += 1
            else:
                round_winner = "User B"
                userB_score += 1

            userA_hand.remove(selected_card_a)
            userB_hand.remove(selected_card_b)

            await ctx.send(f"Round {round_num} winner: {round_winner}")

        except asyncio.TimeoutError:
            await ctx.send("A user took too long to select a card.")
            return

    await determine_final_winner(ctx, userA_score, userB_score, userA, userB, battle)


async def determine_final_winner(ctx, userA_score, userB_score, userA, userB, data):
    if userA_score > userB_score:
        final_winner = f"<@{userA.id}> with {userA_score} points!"
        if userA.id in data["users"]:
            data["users"][userA.id]["points"] += 5
    elif userB_score > userA_score:
        final_winner = f"<@{userB.id}> with {userB_score} points!"
        if userB.id in data["users"]:
            data["users"][userB.id]["points"] += 5
    else:
        final_winner = "It's a draw! Both players have the same score."
    await ctx.send(f"The final winner is: {final_winner}")
    
    save_user_data(data)



@bot.command(name="team")
async def show_team_data(ctx):
    user_id = str(ctx.author.id)

    try:
        user_data = users_collection.find_one({"user_id": user_id})

        if not user_data:
            await ctx.author.send("You have no data yet. Please get your cards first.")
            return

        points = user_data.get('points', 0)
        cards = user_data.get('cards', [])

        embed = discord.Embed(
            title=f"{ctx.author.name}'s Data",
            description=f"Points: {points}",
            color=discord.Color.green()
        )
        await ctx.author.send(embed=embed)

        if cards:
            for card in cards:
                card_name = card.get('name', 'Unknown Card')
                card_rating = card.get('rating', 'N/A')
                card_price = card.get('price', 'N/A')
                card_image_url = card.get('image_url', '')

                card_embed = discord.Embed(
                    title=f"{card_name}",
                    description=f"Rating: {card_rating}\nPrice: {card_price}",
                    color=discord.Color.blue()
                )

                if card_image_url:
                    card_embed.set_image(url=card_image_url)

                await ctx.author.send(embed=card_embed)

        else:
            await ctx.author.send("You don't have any cards yet. Earn or buy cards to build your team.")

    except Exception as e:
        await ctx.author.send(f"An error occurred while fetching your data: {e}")
        print(f"Error in show_team_data: {e}")

@bot.command(name="sell")
async def sell_card(ctx, *, card_name: str):
    user_id = str(ctx.author.id)

    user_data = users_collection.find_one({"user_id": user_id})
    if not user_data:
        await ctx.send(f"{ctx.author.mention}, you do not have an account in the system.")
        return

    card_to_sell = next((card for card in user_data.get("cards", []) if card["name"].lower() == card_name.lower()), None)

    if not card_to_sell:
        await ctx.send(f"{ctx.author.mention}, you don't own a card named '{card_name}'.")
        return
    card_points = card_to_sell.get("price", 0)
    user_points = user_data.get("points", 0)
    new_points = user_points + card_points
    users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"points": new_points},
         "$pull": {"cards": {"name": card_name}}}  
    )

    available_cards_collection.insert_one(card_to_sell)

    await ctx.send(
        f"{ctx.author.mention}, you have successfully sold the card '{card_name}' for {card_points} points!\n"
        f"Your new points total is {new_points}."
    )

@bot.command(name="battlestats") 
async def battlestats(ctx):
    users_data = users_collection.find({})  

    leaderboard = []
    for user in users_data:
        wins = user.get("Wins", 0)
        losses = user.get("Losses", 0)
        matches_played = wins + losses
        leaderboard.append({
            "name": user.get("name", "Unknown")[:15],
            "wins": wins,
            "losses": losses,
            "matches_played": matches_played
        })

    leaderboard.sort(key=lambda x: x["wins"], reverse=True)

    table = PrettyTable()
    table.field_names = ["Rank", "User", "W", "L", "MP"] 


    table.align["Rank"] = "l"  
    table.align["User"] = "l"  
    table.align["W"] = "r"     
    table.align["L"] = "r"     
    table.align["MP"] = "r"    

   
    for rank, user in enumerate(leaderboard, start=1):
        if rank == 1:
            trophy = "🏆"  
        elif rank == 2:
            trophy = "🥈"  
        elif rank == 3:
            trophy = "🥉"  
        else:
            trophy = "" 

        table.add_row([f"{trophy} {rank}", user["name"], user["wins"], user["losses"], user["matches_played"]])


    embed = discord.Embed(
        title="Battle Stats Leaderboard",  
        description=f"```{table}```", 
        color=discord.Color.green()  
    )

    await ctx.send(embed=embed)

@bot.command(name="shop")
async def shop(ctx):
    website_url = "https://www.google.com"
    await ctx.send(f"Visit the shop: {website_url}")

# bot.run(DISCORD_BOT_TOKEN)
@app.route('/')
def home():
    return "Discord Bot is Running!"


def run_flask():
    app.run(host="0.0.0.0", port=int(os.getenv('PORT', 5000)))

def run_bot():
    bot.run(os.getenv('DISCORD_BOT_TOKEN'))

if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()

    run_bot()


