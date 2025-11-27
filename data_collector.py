"""
Data collector module for fetching trade data from Interactive Brokers
and writing it to the CSV file for dashboard visualization.
"""

import logging
import os
import csv
from datetime import datetime
from ib_async import IB, ExecutionFilter


def collect_daily_results(ib: IB, csv_path: str = None, strategy: str = "Unknown"):
    """
    Fetches all executions from IB for the current trading session and appends
    them to the trading results CSV file.

    This function should be called at the end of each trading day, before
    disconnecting from IB Gateway.

    Args:
        ib: Connected IB instance
        csv_path: Optional path to CSV file. If None, uses default location.
        strategy: Strategy name (e.g., "TrendStochRSI", "DeHighInLow")

    Returns:
        int: Number of trades written to CSV
    """
    logger = logging.getLogger(__name__)

    # Default CSV path
    if csv_path is None:
        csv_path = os.path.join(
            os.path.dirname(__file__),
            "data",
            "trading_results.csv"
        )

    # Fetch all executions from IB (current day)
    filter = ExecutionFilter()
    executions = ib.reqExecutions(filter)

    if not executions:
        logger.info("No trades found for today.")
        return 0

    logger.info(f"Found {len(executions)} executions from IB. Processing...")

    # Group executions by permId (permanent order ID)
    # For spreads, all legs of opening trade share same permId
    trades_by_perm_id = {}
    for exec_detail in executions:
        perm_id = exec_detail.execution.permId
        if perm_id not in trades_by_perm_id:
            trades_by_perm_id[perm_id] = []
        trades_by_perm_id[perm_id].append(exec_detail)

    # Process trades and write to CSV
    trades_written = 0
    file_exists = os.path.isfile(csv_path)

    with open(csv_path, 'a', newline='') as csvfile:
        fieldnames = [
            'date', 'trade_type', 'symbol', 'strikes', 'entry_action', 'entry_time', 'entry_price',
            'exit_action', 'exit_price', 'profit', 'status', 'strategy'
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        # Write header if file doesn't exist
        if not file_exists:
            writer.writeheader()

        for perm_id, execs in trades_by_perm_id.items():
            # Sort by execution time
            execs.sort(key=lambda x: x.execution.time)

            # For vertical spreads:
            # - Opening trade has both SLD and BOT legs at same time
            # - Closing trade reverses: BOT what was SLD, SLD what was BOT
            # We need to detect if this is opening or closing by checking timestamps

            # Group by unique execution times (to separate opening from closing)
            times = {}
            for e in execs:
                t = e.execution.time
                if t not in times:
                    times[t] = []
                times[t].append(e)

            # If only one timestamp, this is an opening trade (still open)
            # If multiple timestamps, we have both opening and closing
            time_groups = list(times.values())

            if len(time_groups) == 0:
                continue

            # First time group is the opening trade
            opening_execs = time_groups[0]

            # IB reports both individual leg executions AND a combo-level execution
            # The combo execution has the net price (negative for credit spreads)
            # Individual legs have positive prices

            # Find the combo execution (negative price indicates net credit/debit)
            combo_exec = None
            leg_execs = []

            for e in opening_execs:
                if e.execution.price < 0:
                    # This is the combo net execution
                    combo_exec = e
                else:
                    # These are individual leg executions
                    leg_execs.append(e)

            # Get basic info from combo or first leg
            if combo_exec:
                contract = combo_exec.contract
                execution = combo_exec.execution
                # Always use absolute value - negative means credit received
                entry_price = abs(combo_exec.execution.price)
                entry_action = combo_exec.execution.side
            else:
                # Fallback: calculate from legs if no combo found
                first_exec = opening_execs[0]
                contract = first_exec.contract
                execution = first_exec.execution

                sold_legs = [e for e in leg_execs if e.execution.side == 'SLD']
                bought_legs = [e for e in leg_execs if e.execution.side == 'BOT']

                credit_received = sum(e.execution.price for e in sold_legs)
                debit_paid = sum(e.execution.price for e in bought_legs)
                entry_price = abs(credit_received - debit_paid)
                entry_action = 'BOT' if credit_received > debit_paid else 'SLD'

            # Extract strike prices from ALL executions (legs and combo)
            strikes = []
            for e in opening_execs:
                if hasattr(e.contract, 'strike'):
                    strikes.append(int(e.contract.strike))

            strikes.sort()
            if len(strikes) >= 2:
                strikes_str = f"{strikes[0]}/{strikes[1]}"
            elif len(strikes) == 1:
                strikes_str = str(strikes[0])
            else:
                strikes_str = "unknown"

            # Determine trade type based on option rights in ALL executions
            rights = [e.contract.right for e in opening_execs if hasattr(e.contract, 'right')]
            if 'P' in rights:
                trade_type = 'Bull Put'
            elif 'C' in rights:
                trade_type = 'Bear Call'
            else:
                trade_type = 'unknown'

            # Get entry time
            entry_time = execution.time.astimezone().strftime('%Y-%m-%d %H:%M:%S')
            trade_date = execution.time.astimezone().strftime('%Y-%m-%d')

            # Check if trade is closed (has closing executions)
            if len(time_groups) > 1:
                # Closing trade exists
                closing_execs = time_groups[1]

                # Find combo execution in closing (SLD with negative price means paying to close)
                closing_combo = None
                for e in closing_execs:
                    if e.execution.side == 'SLD' and e.execution.price < 0:
                        closing_combo = e
                        break

                if closing_combo:
                    exit_price = abs(closing_combo.execution.price)
                    exit_action = 'SLD'
                else:
                    # Fallback: calculate from individual legs
                    closing_sold = [e for e in closing_execs if e.execution.side == 'SLD' and e.execution.price > 0]
                    closing_bought = [e for e in closing_execs if e.execution.side == 'BOT' and e.execution.price > 0]

                    closing_credit = sum(e.execution.price for e in closing_sold)
                    closing_debit = sum(e.execution.price for e in closing_bought)
                    exit_price = closing_debit - closing_credit
                    exit_action = 'SLD' if closing_credit > closing_debit else 'BOT'

                # Profit = credit received on entry - debit paid on exit
                profit = (entry_price - exit_price) * 100
                status = 'closed'
            else:
                # Trade is still open
                exit_price = None
                exit_action = ''
                profit = 0.0  # Don't calculate unrealized P&L here
                status = 'open'

            # Write trade row
            writer.writerow({
                'date': trade_date,
                'trade_type': trade_type,
                'symbol': contract.symbol,
                'strikes': strikes_str,
                'entry_action': entry_action,
                'entry_time': entry_time,
                'entry_price': f'{entry_price:.2f}',
                'exit_action': exit_action,
                'exit_price': f'{exit_price:.2f}' if exit_price else '',
                'profit': f'{profit:.2f}',
                'status': status,
                'strategy': strategy
            })

            trades_written += 1
            logger.info(f"Wrote trade: {contract.symbol} {strikes_str} {trade_type} | "
                       f"{entry_action} @ {entry_price:.2f} ({entry_time}) | "
                       f"Status: {status} | Profit: ${profit:.2f}")

    logger.info(f"Successfully wrote {trades_written} trades to {csv_path}")
    return trades_written


def collect_daily_results_simple(ib: IB, csv_path: str = None, strategy: str = "Unknown"):
    """
    Simplified version that writes each execution as a separate row.
    Use this if the grouped version above doesn't match your trading structure.

    Args:
        ib: Connected IB instance
        csv_path: Optional path to CSV file. If None, uses default location.
        strategy: Strategy name (e.g., "TrendStochRSI", "DeHighInLow")

    Returns:
        int: Number of executions written to CSV
    """
    logger = logging.getLogger(__name__)

    if csv_path is None:
        csv_path = os.path.join(
            os.path.dirname(__file__),
            "data",
            "trading_results.csv"
        )

    filter = ExecutionFilter()
    executions = ib.reqExecutions(filter)

    if not executions:
        logger.info("No trades found for today.")
        return 0

    logger.info(f"Found {len(executions)} executions. Writing to CSV...")

    file_exists = os.path.isfile(csv_path)

    with open(csv_path, 'a', newline='') as csvfile:
        fieldnames = [
            'date', 'trade_type', 'symbol', 'strikes', 'entry_action', 'entry_time', 'entry_price',
            'exit_action', 'exit_price', 'profit', 'status', 'strategy'
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        if not file_exists:
            writer.writeheader()

        for exec_detail in executions:
            contract = exec_detail.contract
            execution = exec_detail.execution

            exec_time = execution.time.astimezone().strftime('%Y-%m-%d %H:%M:%S')
            trade_date = execution.time.astimezone().strftime('%Y-%m-%d')

            # Determine if entry or exit
            is_entry = execution.side == 'SLD'

            # Get strike if available
            strike = str(int(contract.strike)) if hasattr(contract, 'strike') else ''

            writer.writerow({
                'date': trade_date,
                'trade_type': 'spread_leg',
                'symbol': contract.symbol,
                'strikes': strike,
                'entry_action': execution.side if is_entry else '',
                'entry_time': exec_time if is_entry else '',
                'entry_price': f'{execution.price:.2f}' if is_entry else '',
                'exit_action': execution.side if not is_entry else '',
                'exit_price': f'{execution.price:.2f}' if not is_entry else '',
                'profit': '',
                'status': 'executed',
                'strategy': strategy
            })

    logger.info(f"Wrote {len(executions)} executions to {csv_path}")
    return len(executions)


if __name__ == "__main__":
    """
    Standalone execution: Connect to IB Gateway, fetch trades, and write to CSV.

    Usage:
        python data_collector.py

    Make sure IB Gateway is running on localhost:4002 before executing.
    """
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))

    from ib_async import util
    from core.gateway import connect_to_ib
    from config import Config

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    logger = logging.getLogger(__name__)
    logger.info("Starting trade data collection...")

    # Connect to IB Gateway
    ib = connect_to_ib(
        host=Config.HOST,
        port=Config.PORT,
        clientID=Config.CLIENT_ID,
        connect_to_tws=Config.CONNECT_TO_TWS
    )

    if ib is None:
        logger.error("Failed to connect to IB Gateway. Exiting.")
        sys.exit(1)

    try:
        # Get strategy name from Config
        strategy_name = Config.STRATEGY_TYPE if hasattr(Config, 'STRATEGY_TYPE') else "Unknown"
        logger.info(f"Using strategy: {strategy_name}")

        # Collect and write trade data
        trades_written = collect_daily_results(ib, strategy=strategy_name)
        logger.info(f"Data collection complete. {trades_written} trades written to CSV.")
    except Exception as e:
        logger.exception("Error during data collection")
    finally:
        # Disconnect from IB
        logger.info("Disconnecting from IB Gateway...")
        ib.disconnect()