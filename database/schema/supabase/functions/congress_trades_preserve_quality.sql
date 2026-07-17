CREATE OR REPLACE FUNCTION public.congress_trades_preserve_quality()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
  IF OLD.quality_status IN ('garbage', 'corrected') THEN
    IF COALESCE(current_setting('app.force_quality_update', true), '') IS DISTINCT FROM 'true' THEN
      NEW.quality_status := OLD.quality_status;
      NEW.quality_reason := OLD.quality_reason;
      NEW.suggested_ticker := OLD.suggested_ticker;
      IF OLD.replacement_trade_id IS NOT NULL THEN
        NEW.replacement_trade_id := OLD.replacement_trade_id;
      END IF;
    END IF;
  END IF;
  RETURN NEW;
END;
$function$;