using System;

public class ScorePacket
{
	public long Score;

	public bool IsInfinite;

	public bool IsNegative;

	public ScorePacket(long score)
	{
		Score = score;
		IsInfinite = false;
		IsNegative = score < 0;
	}

	public ScorePacket(bool isNegative)
	{
		Score = 0L;
		IsInfinite = true;
		IsNegative = isNegative;
	}

	private static ScorePacket Infinite(bool negative)
	{
		return new ScorePacket(negative);
	}

	public static ScorePacket operator +(ScorePacket a, ScorePacket b)
	{
		if (a.IsInfinite || b.IsInfinite)
		{
			if (a.IsInfinite && b.IsInfinite && a.IsNegative != b.IsNegative)
			{
				return new ScorePacket(0L);
			}
			if (!a.IsInfinite)
			{
				return b;
			}
			return a;
		}
		try
		{
			return new ScorePacket(checked(a.Score + b.Score));
		}
		catch (OverflowException)
		{
			return Infinite((a.Score < 0 && b.Score <= 0) || (a.Score <= 0 && b.Score < 0));
		}
	}

	public static ScorePacket operator +(ScorePacket a, long b)
	{
		return a + new ScorePacket(b);
	}

	public static ScorePacket operator +(long a, ScorePacket b)
	{
		return new ScorePacket(a) + b;
	}

	public static ScorePacket operator -(ScorePacket a, ScorePacket b)
	{
		if (a.IsInfinite || b.IsInfinite)
		{
			if (a.IsInfinite && b.IsInfinite && a.IsNegative == b.IsNegative)
			{
				return new ScorePacket(0L);
			}
			if (a.IsInfinite)
			{
				return a;
			}
			return Infinite(!b.IsNegative);
		}
		try
		{
			return new ScorePacket(checked(a.Score - b.Score));
		}
		catch (OverflowException)
		{
			return Infinite(a.Score - b.Score < 0);
		}
	}

	public static ScorePacket operator -(ScorePacket a, long b)
	{
		return a - new ScorePacket(b);
	}

	public static ScorePacket operator -(long a, ScorePacket b)
	{
		return new ScorePacket(a) - b;
	}

	public static ScorePacket operator *(ScorePacket a, ScorePacket b)
	{
		if (a.IsInfinite && b.IsInfinite)
		{
			return Infinite(a.IsNegative != b.IsNegative);
		}
		if (a.IsInfinite || b.IsInfinite)
		{
			if ((a.IsInfinite && b.Score == 0L) || (b.IsInfinite && a.Score == 0L))
			{
				return new ScorePacket(0L);
			}
			return Infinite((a.IsInfinite ? a.IsNegative : b.IsNegative) ^ (a.IsInfinite ? (b.Score < 0) : (a.Score < 0)));
		}
		try
		{
			return new ScorePacket(checked(a.Score * b.Score));
		}
		catch (OverflowException)
		{
			return Infinite((a.Score < 0) ^ (b.Score < 0));
		}
	}

	public static ScorePacket operator *(ScorePacket a, long b)
	{
		return a * new ScorePacket(b);
	}

	public static ScorePacket operator *(long a, ScorePacket b)
	{
		return new ScorePacket(a) * b;
	}

	public static ScorePacket operator /(ScorePacket a, ScorePacket b)
	{
		if (b.Score == 0L && !b.IsInfinite)
		{
			throw new DivideByZeroException();
		}
		if (a.IsInfinite)
		{
			return Infinite(a.IsNegative ^ b.IsNegative);
		}
		if (b.IsInfinite)
		{
			return new ScorePacket(0L);
		}
		if (a.Score == long.MinValue && b.Score == -1)
		{
			return Infinite(negative: false);
		}
		return new ScorePacket(a.Score / b.Score);
	}

	public static ScorePacket operator /(ScorePacket a, long b)
	{
		return a / new ScorePacket(b);
	}

	public static ScorePacket operator /(long a, ScorePacket b)
	{
		return new ScorePacket(a) / b;
	}

	public static bool operator >(ScorePacket a, ScorePacket b)
	{
		if (a.IsInfinite && b.IsInfinite)
		{
			if (!a.IsNegative)
			{
				return b.IsNegative;
			}
			return false;
		}
		if (a.IsInfinite)
		{
			return !a.IsNegative;
		}
		if (b.IsInfinite)
		{
			return b.IsNegative;
		}
		return a.Score > b.Score;
	}

	public static bool operator <(ScorePacket a, ScorePacket b)
	{
		return b > a;
	}

	public static bool operator >=(ScorePacket a, ScorePacket b)
	{
		return !(a < b);
	}

	public static bool operator <=(ScorePacket a, ScorePacket b)
	{
		return !(a > b);
	}

	public static bool operator ==(ScorePacket a, ScorePacket b)
	{
		if ((object)a == b)
		{
			return true;
		}
		if ((object)a == null || (object)b == null)
		{
			return false;
		}
		if (a.IsInfinite || b.IsInfinite)
		{
			if (a.IsInfinite == b.IsInfinite)
			{
				return a.IsNegative == b.IsNegative;
			}
			return false;
		}
		return a.Score == b.Score;
	}

	public static bool operator !=(ScorePacket a, ScorePacket b)
	{
		return !(a == b);
	}

	public bool Equals(ScorePacket other)
	{
		return this == other;
	}

	public override bool Equals(object obj)
	{
		if (obj is ScorePacket other)
		{
			return Equals(other);
		}
		return false;
	}

	public override int GetHashCode()
	{
		if (!IsInfinite)
		{
			return Score.GetHashCode();
		}
		return HashCode.Combine(IsInfinite, IsNegative);
	}

	public int CompareTo(ScorePacket other)
	{
		if (this > other)
		{
			return 1;
		}
		if (this < other)
		{
			return -1;
		}
		return 0;
	}

	public override string ToString()
	{
		if (IsInfinite)
		{
			if (!IsNegative)
			{
				return "<font=NotoSansJPBold SDF>∞</font>";
			}
			return "-<font=NotoSansJPBold SDF>∞</font>";
		}
		return Score.ToString();
	}

	public static ScorePacket Max(ScorePacket a, ScorePacket b)
	{
		if (!(a > b))
		{
			return b;
		}
		return a;
	}

	public float ToFraction(ScorePacket max)
	{
		if (IsInfinite)
		{
			if (!IsNegative)
			{
				return 1f;
			}
			return 0f;
		}
		if (max.IsInfinite)
		{
			return 0f;
		}
		return (float)Score / (float)max.Score;
	}

	public ScorePacket Scale(float factor)
	{
		if (IsInfinite)
		{
			return this;
		}
		return new ScorePacket((long)Math.Round((float)Score * factor));
	}

	public ScorePacket GetAbsoluteValue()
	{
		return new ScorePacket(isNegative: false)
		{
			Score = ((Score >= 0) ? Score : (Score * -1)),
			IsInfinite = IsInfinite
		};
	}
}
