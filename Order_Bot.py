import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
import csv
import json
from datetime import datetime
import re


# test test test
# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# States for conversation
CUSTOMER_NAME, ITEM_INPUT = range(2)

class OrderBot:
    def __init__(self):
        self.item_catalog = {}
        self.customer_data = {}
        self.current_orders = {}  # Store orders by user_id
        self.load_all_data()

    def load_all_data(self):
        self.item_catalog = self.load_item_catalog('item_catalog.csv')
        self.customer_data = self.load_customer_data('customer.csv')

    def load_item_catalog(self, file_name):
        item_catalog = {}
        try:
            with open(file_name, mode='r', encoding='utf-8-sig') as file:
                header = next(file).strip().split(',')
                for line in file:
                    try:
                        row = line.strip().split(',')
                        item_code = row[0]
                        item_name = row[1]
                        
                        prices = {}
                        if row[2]:  # price_1_0
                            prices[1.0] = int(row[2])
                        if len(row) > 3 and row[3]:  # price_0_5
                            prices[0.5] = int(row[3])
                        if len(row) > 4 and row[4]:  # price_0_25
                            prices[0.25] = int(row[4])
                        
                        item_catalog[item_code.upper()] = {
                            'name': item_name,
                            'prices': prices
                        }
                    except Exception as e:
                        logger.error(f"Error processing item {row[0] if row else 'unknown'}: {str(e)}")
                        continue
            return item_catalog
        except FileNotFoundError:
            logger.error(f"The file '{file_name}' was not found.")
            return {}

    def load_customer_data(self, file_name):
        customer_data = {}
        try:
            with open(file_name, mode='r', encoding='utf-8') as file:
                csv_reader = csv.DictReader(file)
                for row in csv_reader:
                    try:
                        usps_value = int(row['usps'])
                    except ValueError:
                        usps_value = 0
                    customer_data[row['name'].lower()] = {
                        'shipping_name': row['shipping_name'],
                        'address': row['address'].replace("\\n", "\n"),
                        'usps': usps_value
                    }
            return customer_data
        except FileNotFoundError:
            logger.error(f"The file '{file_name}' was not found.")
            return {}

    def determine_size_and_price(self, item_code, quantity):
        item = self.item_catalog[item_code]
        prices = item['prices']
        quantity = float(quantity)
        
        if quantity >= 1.0:
            size = 1.0
        elif quantity >= 0.5:
            size = 0.5
        else:
            size = 0.25
            
        if size not in prices:
            available_sizes = sorted(prices.keys())
            for available_size in available_sizes:
                if available_size > size:
                    size = available_size
                    break
            if size not in prices:
                raise ValueError(f"No suitable size available for quantity {quantity}")
        
        price = prices[size]
        total_price = price * (quantity / size)
        
        return size, total_price

    def format_price(self, price):
        return f"${int(round(price))}"

    def get_order_summary(self, user_id):
        if user_id not in self.current_orders:
            return "No active order."
        
        order = self.current_orders[user_id]
        current_date = datetime.now().strftime("%m/%d")
        customer_name = order['customer_name'].strip().title()
        total_sum = sum(item['total_price'] for item in order['items'])
        
        summary = f"{current_date}\n#\n{customer_name}\n\n"
        
        for item in order['items']:
            summary += f"#{item['code']} / {item['quantity']} P {self.item_catalog[item['code']]['name']} = {self.format_price(item['total_price'])}\n"
        
        if total_sum <= 500:
            summary += "\nSmall Shipping $25\n"
            total_with_shipping = total_sum + 25
        else:
            total_with_shipping = total_sum
        
        total_pounds = sum(float(item['quantity']) for item in order['items'])
        if total_pounds <= 1:
            summary += "1 Free Edible\n"
        
        summary += f"\nTotal: {self.format_price(total_with_shipping)}\n\nAddress:\n"
        
        customer_info = self.customer_data.get(customer_name.lower(), None)
        if customer_info:
            if customer_info['usps'] == 1:
                summary += "!! USPS !!\n\n"
            else:
                summary += "\n"
            
            if customer_info['shipping_name']:
                summary += f"{customer_info['shipping_name']}\n\n"
            summary += f"{customer_info['address']}\n"
        
        summary += "\nPaid:\n"
        return summary

# Initialize bot
order_bot = OrderBot()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to the Order Management System!\n"
        "Please enter the customer name to start a new order."
    )
    return CUSTOMER_NAME

async def handle_customer_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    customer_name = update.message.text.strip()
    user_id = update.effective_user.id
    
    if not customer_name:
        await update.message.reply_text("Please enter a valid customer name.")
        return CUSTOMER_NAME
    
    customer_name_formatted = customer_name.title()
    customer_info = order_bot.customer_data.get(customer_name.lower(), None)
    
    if not customer_info:
        # Handle new customer
        with open('new_customers.csv', mode='a', newline='') as file:
            csv_writer = csv.writer(file)
            csv_writer.writerow([customer_name_formatted])
    
    # Initialize new order for this user
    order_bot.current_orders[user_id] = {
        'customer_name': customer_name,
        'items': []
    }
    
    await update.message.reply_text(
        f"Starting order for {customer_name_formatted}\n"
        "Enter items in format: ITEMCODE QUANTITY\n"
        "Example: S755 1\n"
        "Type 'done' to complete the order or 'cancel' to cancel."
    )
    return ITEM_INPUT

async def handle_item_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().upper()
    user_id = update.effective_user.id
    
    if text == 'DONE':
        summary = order_bot.get_order_summary(user_id)
        await update.message.reply_text(summary)
        order_bot.current_orders.pop(user_id, None)
        return ConversationHandler.END
    
    if text == 'CANCEL':
        order_bot.current_orders.pop(user_id, None)
        await update.message.reply_text("Order cancelled.")
        return ConversationHandler.END
    
    try:
        item_code, quantity = text.split()
        if item_code not in order_bot.item_catalog:
            await update.message.reply_text(f"Item code '{item_code}' not recognized")
            return ITEM_INPUT
        
        try:
            quantity = float(quantity)
            if quantity <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("Please enter a valid quantity")
            return ITEM_INPUT
        
        size, total_price = order_bot.determine_size_and_price(item_code, quantity)
        
        order_bot.current_orders[user_id]['items'].append({
            'code': item_code,
            'quantity': quantity,
            'size': size,
            'total_price': total_price
        })
        
        await update.message.reply_text(
            f"Added: {item_code} - {quantity}P - {order_bot.format_price(total_price)}\n"
            f"Enter next item or type 'done' to complete order."
        )
        
    except ValueError as e:
        await update.message.reply_text(
            "Invalid format. Please use: ITEMCODE QUANTITY\n"
            "Example: S755 1"
        )
    
    return ITEM_INPUT

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    order_bot.current_orders.pop(user_id, None)
    await update.message.reply_text("Order cancelled.")
    return ConversationHandler.END

def main():
    # Replace 'YOUR_BOT_TOKEN' with the token you get from BotFather
    application = Application.builder().token('7249575537:AAFcJr9nKa0auzhMGRbUJZ_kOqijbazr8Uw').build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            CUSTOMER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_customer_name)],
            ITEM_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_item_input)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    application.add_handler(conv_handler)
    
    # Start the bot
    print("Bot is starting...")
    application.run_polling()

if __name__ == '__main__':
    main()
